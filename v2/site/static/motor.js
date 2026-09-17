/* motor.js - de keten starten en er platen doorheen sturen.
 *
 * Hierachter zitten twee workers en een stuk gedeeld geheugen (zie
 * motor/py-werker.js en motor/ort-werker.js). Dat hoeft het scherm niet te
 * weten: hier is het `await start()` en `await verwerk(fotos)`.
 *
 * Eén motor per tabblad, met opzet. Pyodide plus OpenCV plus de drie modellen
 * is een paar honderd megabyte werkgeheugen; twee keer opstarten om twee
 * platen tegelijk te doen maakt het niet sneller maar sloopt een telefoon.
 * Platen gaan er dus één voor één doorheen, en dat is precies wat de wachtrij
 * al aanneemt.
 */

const WORTEL = new URL("../motor", import.meta.url).href.replace(/\/$/, "");

/* De brug tussen Python en onnxruntime-web. Een detectie op 1800 px is
 * 1800*1800*3*4 = 38,9 MB in en 13 MB uit; 64/40 dekt dat met marge. Dit
 * geheugen wordt bij het starten echt gereserveerd, dus ruimer is op een
 * telefoon niet gratis. Lees je op een grotere zijde, dan moet dit mee -
 * ocr_brug.py geeft daar een leesbare fout over in plaats van om te vallen. */
const IN_MB = 64, UIT_MB = 40;

let motor = null;

export const staat = () => (motor ? motor.staat : "uit");
export const isKlaar = () => !!motor && motor.staat === "klaar";

/** Start de keten. Meldt onderweg welke stap hij zet.
 *
 *  Veilig om twee keer aan te roepen: de tweede aanroep krijgt dezelfde
 *  belofte terug in plaats van een tweede Pyodide op te starten. */
export function start(opMelding = () => {}) {
  if (motor) return motor.gereed;

  if (typeof SharedArrayBuffer === "undefined") {
    return Promise.reject(new Error(
      "Deze pagina draait niet cross-origin geisoleerd, dus er is geen gedeeld "
      + "geheugen. De server moet cross-origin-opener-policy: same-origin en "
      + "cross-origin-embedder-policy: require-corp meesturen."));
  }

  const ctrl = new SharedArrayBuffer(64);
  const invoer = new SharedArrayBuffer(IN_MB * 1024 * 1024);
  const uitvoer = new SharedArrayBuffer(UIT_MB * 1024 * 1024);
  const lijn = new MessageChannel();
  const draden = Math.max(1, Math.min(navigator.hardwareConcurrency || 4, 8));

  const ort = new Worker(new URL("./motor/ort-werker.js", import.meta.url),
                         { type: "module" });
  const py = new Worker(new URL("./motor/py-werker.js", import.meta.url));

  motor = { py, ort, staat: "starten", bezig: null, gereed: null };

  ort.postMessage({ soort: "opzet", wortel: `${WORTEL}/modellen`,
                    ctrl, invoer, uitvoer, draden, poort: lijn.port2 },
                  [lijn.port2]);
  ort.postMessage({ soort: "warm", welke: ["det", "cls", "rec"] });

  motor.gereed = new Promise((klaar, fout) => {
    py.onmessage = e => {
      const b = e.data;
      if (b.soort === "stap") return opMelding({ soort: "stap", tekst: b.tekst });
      if (b.soort === "uit") return opMelding({ soort: "uit", tekst: b.tekst });
      if (b.soort === "voortgang") {
        // Hoort bij de plaat die onderweg is, niet bij het opstarten.
        if (motor.bezig && motor.bezig.opVoortgang) motor.bezig.opVoortgang(b);
        return opMelding(b);
      }

      if (b.soort === "klaar") {
        motor.staat = "klaar";
        return klaar({ versie: b.versie, cv2: b.cv2 });
      }
      // Een antwoord op een plaat, of een fout. Allebei horen bij de plaat die
      // op dit moment onderweg is.
      if (motor.bezig) {
        const { op, af } = motor.bezig;
        motor.bezig = null;
        if (b.soort === "plaat") op(b.uitslag);
        else if (b.soort === "fout") af(new Error(b.bericht));
        return;
      }
      if (b.soort === "fout") {
        motor.staat = "stuk";
        fout(new Error(b.bericht));
      }
    };
    py.onerror = e => {
      motor.staat = "stuk";
      fout(new Error(e.message || "de motor viel om"));
    };
    py.postMessage({ soort: "start", wortel: WORTEL, ctrl, invoer, uitvoer,
                     poort: lijn.port1 }, [lijn.port1]);
  });

  return motor.gereed;
}

/** Eén plaat door de keten. `fotos` is [{naam, blob}], voorkant eerst.
 *
 *  Geeft terug wat plaat.verwerk() opleverde: de plaat als hij herkend is, de
 *  reden als dat niet lukte, en de uitgesneden hoezen. */
export async function verwerk(fotos, opties = {}) {
  if (!isKlaar()) throw new Error("de motor draait niet");
  if (motor.bezig) throw new Error("er is al een plaat onderweg");

  const bytes = [];
  for (const f of fotos) {
    bytes.push([f.naam, await f.blob.arrayBuffer()]);
  }

  return new Promise((op, af) => {
    motor.bezig = { op, af, opVoortgang: opties.opVoortgang };
    motor.py.postMessage(
      { soort: "plaat", fotos: bytes, token: opties.token || null,
        leespx: opties.leespx || 1800, prijzen: opties.prijzen !== false },
      bytes.map(b => b[1]));
  });
}

/** De motor afbreken. Alleen als de gebruiker er echt vanaf wil: opnieuw
 *  starten kost weer de hele opstart en, als de cache leeg is, 40 MB. */
export function stop() {
  if (!motor) return;
  motor.py.terminate();
  motor.ort.terminate();
  motor = null;
}
