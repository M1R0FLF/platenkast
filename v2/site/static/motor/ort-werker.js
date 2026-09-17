/* ort-werker.js - de drie ONNX-modellen, en verder niets.
 *
 * Deze worker bestaat omdat RapidOCR SYNCHROON aanroept en onnxruntime-web
 * ASYNCHROON antwoordt. Dat is niet te overbruggen binnen een draad: een
 * `await` midden in `TextDetector.__call__` bestaat niet, en die functie
 * herschrijven is precies wat we niet willen - dan is het niet meer dezelfde
 * code die de metingen heeft opgeleverd.
 *
 * Dus twee draden. De Pyodide-worker legt zijn invoer in gedeeld geheugen en
 * gaat op `Atomics.wait` staan, dus hij blokkeert echt - voor Python voelt het
 * als een gewone functieaanroep die even duurt. Deze worker wordt wakker van
 * het bericht, rekent op zijn eigen draad, schrijft het antwoord terug in
 * gedeeld geheugen en tikt de ander wakker.
 *
 * Gedeeld geheugen vraagt SharedArrayBuffer, en dat vraagt cross-origin-
 * isolatie (COOP + COEP). Dat is hier geen prijs maar winst: dezelfde isolatie
 * zet ook WASM-threads aan, en daar komt op een telefoon de snelheid vandaan.
 */
import * as ort from "https://cdn.jsdelivr.net/npm/onnxruntime-web@1.23.0/dist/ort.wasm.min.mjs";

ort.env.wasm.wasmPaths = "https://cdn.jsdelivr.net/npm/onnxruntime-web@1.23.0/dist/";
ort.env.wasm.simd = true;
ort.env.logLevel = "error";

const MODEL = {
  det: "ch_PP-OCRv3_det_infer.onnx",
  rec: "ch_PP-OCRv3_rec_infer.onnx",
  cls: "ch_ppocr_mobile_v2.0_cls_infer.onnx",
};

let ctrl, invoer, uitvoer;        // vensters op het gedeelde geheugen
const sessie = {};
let wortel = "";

/** De eerste aanroep van een model laadt hem; de rest hergebruikt.
 *
 *  Met opzet lui: wie alleen de stand van een hoes bepaalt raakt `rec` nooit
 *  aan, en dat is het model van 10,7 MB. */
async function laad(naam) {
  if (!sessie[naam]) {
    sessie[naam] = await ort.InferenceSession.create(`${wortel}/${MODEL[naam]}`, {
      executionProviders: ["wasm"],
      graphOptimizationLevel: "all",
    });
  }
  return sessie[naam];
}

function meldFout(bericht) {
  // De tekst gaat mee terug in de uitvoerbuffer, anders weet de Python-kant
  // alleen DAT het misging. Een stille fout in de OCR is het ergste wat hier
  // kan gebeuren: dan lijkt een hoes gewoon leeg.
  const rauw = new TextEncoder().encode(bericht);
  new Uint8Array(uitvoer.buffer).set(rauw.subarray(0, uitvoer.buffer.byteLength));
  Atomics.store(ctrl, 1, rauw.length);
  Atomics.store(ctrl, 0, 2);
  Atomics.notify(ctrl, 0);
}

async function draai({ naam, vorm, aantal }) {
  try {
    const s = await laad(naam);
    const t = new ort.Tensor("float32", invoer.subarray(0, aantal), vorm);
    const uit = await s.run({ [s.inputNames[0]]: t });
    const y = uit[s.outputNames[0]];

    if (y.data.length > uitvoer.length) {
      return meldFout(`uitvoer past niet: ${y.data.length} floats, `
                    + `buffer is ${uitvoer.length}`);
    }
    uitvoer.set(y.data);
    Atomics.store(ctrl, 1, y.data.length);
    Atomics.store(ctrl, 2, y.dims.length);
    y.dims.forEach((d, i) => Atomics.store(ctrl, 3 + i, d));
    Atomics.store(ctrl, 0, 1);
    Atomics.notify(ctrl, 0);
  } catch (e) {
    meldFout(`${naam}: ${e && e.message ? e.message : e}`);
  }
}

self.onmessage = async ev => {
  const b = ev.data;
  if (b.soort === "opzet") {
    wortel = b.wortel;
    ctrl = new Int32Array(b.ctrl);
    invoer = new Float32Array(b.invoer);
    uitvoer = new Float32Array(b.uitvoer);
    ort.env.wasm.numThreads = b.draden;
    b.poort.onmessage = e => draai(e.data);      // de lijn naar Pyodide
    self.postMessage({ soort: "klaar" });
    return;
  }
  if (b.soort === "warm") {
    // Modellen vast inladen terwijl de gebruiker nog een foto kiest, zodat de
    // eerste hoes niet 900ms extra kost.
    try {
      await Promise.all((b.welke || ["det", "cls"]).map(laad));
      self.postMessage({ soort: "warm-klaar" });
    } catch (e) {
      self.postMessage({ soort: "warm-fout", fout: String(e) });
    }
  }
};
