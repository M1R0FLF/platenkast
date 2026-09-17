/* py-werker.js - CPython in de browser, met de keten erin.
 *
 * Hier draait Pyodide: CPython 3.13 naar WASM, met numpy en OpenCV 4.11. Dat
 * is genoeg om knip, foto, groep, velden, match, beeld, discogs en prijs
 * ONVERANDERD te draaien - dezelfde bestanden die `py run.py` op de PC
 * gebruikt, gekopieerd door bundel.py.
 *
 * Dat is de kern van de keuze. De nauwkeurigheid van dit project zit in
 * afgestelde drempels die met de hand gemeten zijn: 92 juiste persingen op 35
 * tot 766 samenvallende punten, 5 foute op hoogstens 8. Die code overzetten
 * naar JavaScript betekent die metingen opnieuw doen, en elk verschil is een
 * verkeerde persing die niemand meer opmerkt. Dus wordt er niets overgezet.
 *
 * Deze worker praat met ort-werker.js over gedeeld geheugen (zie ocr_brug.py
 * voor waarom dat moet). Hij blokkeert daarbij op `Atomics.wait`, en dat mag
 * hier juist wel: een worker heeft geen scherm dat ondertussen moet blijven
 * reageren.
 */
let pyodide = null;
let ctrl, invoerBytes, uitvoerBytes;
let naarOrt;                          // MessagePort naar de rekenwerker
let wortel = "";

const zeg = (soort, velden = {}) => self.postMessage({ soort, ...velden });

/* --------------------------------------------------------------- de brug -- */

/** Synchroon een tensor door een model. Aangeroepen vanuit Python.
 *
 *  De volgorde is de hele truc: eerst het seinvlaggetje op 0, DAN pas het
 *  bericht versturen. Andersom kan de rekenwerker klaar zijn voor wij gaan
 *  wachten, en dan wachten we op een tik die al geweest is - een vastloper die
 *  zich alleen voordoet als het toevallig snel ging, dus precies het soort dat
 *  je pas in productie tegenkomt.
 */
function brugVraag(naam, vorm, aantal) {
  Atomics.store(ctrl, 0, 0);
  naarOrt.postMessage({ naam, vorm: Array.from(vorm), aantal });
  Atomics.wait(ctrl, 0, 0);

  const status = Atomics.load(ctrl, 0);
  const lengte = Atomics.load(ctrl, 1);
  if (status !== 1) {
    const rauw = new Uint8Array(uitvoerBytes.buffer, 0, lengte);
    return [status, 0, new TextDecoder().decode(rauw)];
  }
  const ndim = Atomics.load(ctrl, 2);
  const dims = [];
  for (let i = 0; i < ndim; i++) dims.push(Atomics.load(ctrl, 3 + i));
  return [1, lengte, dims];
}

/* ------------------------------------------------------------------ start -- */

async function start(b) {
  wortel = b.wortel;
  ctrl = new Int32Array(b.ctrl);
  invoerBytes = new Float32Array(b.invoer);
  uitvoerBytes = new Float32Array(b.uitvoer);
  naarOrt = b.poort;

  zeg("stap", { tekst: "Python ophalen" });
  importScripts("https://cdn.jsdelivr.net/pyodide/v0.28.3/full/pyodide.js");
  pyodide = await loadPyodide({
    indexURL: "https://cdn.jsdelivr.net/pyodide/v0.28.3/full/",
    stdout: t => zeg("uit", { tekst: t }),
    stderr: t => zeg("uit", { tekst: t }),
  });

  zeg("stap", { tekst: "numpy, OpenCV, shapely, pyclipper" });
  await pyodide.loadPackage(
    ["numpy", "opencv-python", "pyclipper", "shapely", "pyyaml", "six", "pillow"],
    { messageCallback: () => {} });

  // De brug op de globale JS-scope; Python haalt ze op met `import js`.
  self.brugVraag = brugVraag;
  self.brugInvoer = invoerBytes;
  self.brugUitvoer = uitvoerBytes;
  self.brugTekenset = await (await fetch(`${wortel}/modellen/tekenset.txt`)).text();

  zeg("stap", { tekst: "de keten inladen" });
  const bestanden = await (await fetch(`${wortel}/py/bestanden.json`)).json();
  const FS = pyodide.FS;
  FS.mkdirTree("/keten");
  await Promise.all(bestanden.map(async pad => {
    const tekst = await (await fetch(`${wortel}/py/${pad}`)).text();
    const map = pad.includes("/") ? `/keten/${pad.slice(0, pad.lastIndexOf("/"))}` : "/keten";
    FS.mkdirTree(map);
    FS.writeFile(`/keten/${pad}`, tekst);
  }));

  zeg("stap", { tekst: "de OCR aansluiten" });
  await pyodide.runPythonAsync(`
import sys
sys.path.insert(0, "/keten")

import ocr_brug
gezet = ocr_brug.installeer()

# Niet aannemen dat het gelukt is. Als rapidocr straks toch het echte
# OrtInferSession pakt, valt hij om op een onnxruntime die niet bestaat - en
# dat wil je hier weten, met deze melding, en niet tien seconden later midden
# in een hoes.
import rapidocr_onnxruntime.utils as _ru
assert _ru.OrtInferSession is ocr_brug.OrtInferSession, "de brug zit er niet in"

import knip
_ = knip.motor()          # laadt RapidOCR; hier valt het om als er iets mist
print("keten klaar:", knip.VERSIE)
`);

  zeg("klaar", {
    versie: pyodide.runPython("import sys; sys.version.split()[0]"),
    cv2: pyodide.runPython("import cv2; cv2.__version__"),
  });
}

/* ------------------------------------------------------------------ werk -- */

async function lees(b) {
  // De foto komt binnen als bytes en gaat als bytes naar Python. Geen canvas,
  // geen herkleuring onderweg: cv2.imdecode leest exact dezelfde JPEG als
  // cv2.imread op de PC, en dat is het enige dat garandeert dat er hetzelfde
  // uitkomt.
  pyodide.FS.writeFile("/werk.jpg", new Uint8Array(b.bytes));
  const t0 = performance.now();
  const uit = await pyodide.runPythonAsync(`
import json, cv2, numpy as np, knip
img = cv2.imread("/werk.jpg", cv2.IMREAD_COLOR)
if img is None:
    raise ValueError("die foto kon niet gelezen worden")

res, _t = knip.motor()(img)
regels = [{"t": r[1], "z": float(r[2])} for r in (res or [])]
json.dumps({"vorm": list(img.shape), "regels": regels,
            "tekst": "\\n".join(r["t"] for r in regels)})
`);
  zeg("gelezen", { uitslag: JSON.parse(uit), ms: Math.round(performance.now() - t0) });
}

/** Wat `match.py` uit een OCR-tekst haalt.
 *
 *  Dit is de vergelijking die telt. Of de browser exact dezelfde LETTERS
 *  produceert is niet de vraag - de vraag is of er dezelfde PERSING uitkomt,
 *  en daar staan deze velden tussenin. Vooral `tracktermen` is gevoelig: die
 *  neemt alleen regels met een spatie erin, dus waar de ene RapidOCR plakt en
 *  de andere niet, verandert de zoekopdracht.
 */
async function velden(b) {
  pyodide.globals.set("_tekst_a", b.a);
  pyodide.globals.set("_tekst_b", b.b);
  const uit = await pyodide.runPythonAsync(`
import json, velden

def uit(t):
    rec = {"ocr_achterkant": t, "ocr_voorkant": "", "ocr_hoekstrook": "", "koptekst": []}
    d = velden.uit_tekst(t)
    d["woordtermen"] = velden.woordtermen(rec)
    d["tracktermen"] = velden.tracktermen(rec)
    d["kaal"] = velden.kaal(t)
    return d

json.dumps({"a": uit(_tekst_a), "b": uit(_tekst_b)})
`);
  zeg("velden", { uitslag: JSON.parse(uit) });
}

self.onmessage = async ev => {
  const b = ev.data;
  try {
    if (b.soort === "start") return await start(b);
    if (b.soort === "lees") return await lees(b);
    if (b.soort === "velden") return await velden(b);
  } catch (e) {
    zeg("fout", { bericht: e && e.message ? e.message : String(e) });
  }
};
