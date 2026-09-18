/* opslag.js - waar de kast staat.
 *
 * Twee lagen die met opzet gescheiden blijven:
 *
 *   collectie   wat de keten uitrekende. Wegwerpbaar: draai je opnieuw, dan
 *               wordt dit vervangen.
 *   eigen       wat JIJ erover zegt: staat, eigen vraagprijs, notitie,
 *               verkocht of niet. Dit overleeft elke nieuwe run.
 *
 * Dat onderscheid is de hele reden dat dit bestand bestaat. Zet je ze in een
 * record, dan wist een tweede import van dezelfde foto's stilletjes de conditie
 * die je zelf had ingevuld, en dat merk je pas als het weg is.
 *
 * De buitenkant (laad/bewaar/zetEigen) is met opzet dom en async, zodat er
 * later een cloud achter kan zonder dat de schermen veranderen.
 */

const NAAM = "platenkast";
const VERSIE = 2;                      // 2: wachtrij erbij

let _db = null;

function open() {
  if (_db) return _db;
  _db = new Promise((klaar, fout) => {
    const v = indexedDB.open(NAAM, VERSIE);
    v.onupgradeneeded = () => {
      const db = v.result;
      if (!db.objectStoreNames.contains("collectie"))
        db.createObjectStore("collectie", { keyPath: "id" });
      if (!db.objectStoreNames.contains("eigen"))
        db.createObjectStore("eigen", { keyPath: "id" });
      if (!db.objectStoreNames.contains("meta"))
        db.createObjectStore("meta", { keyPath: "sleutel" });
      // De wachtrij: platen die nog verwerkt moeten worden, met hun foto's er
      // IN. Niet als los bestand ernaast, want dan raakt het een keer uit
      // elkaar; en niet in geheugen, want de hele reden dat dit een wachtrij is
      // is dat je de app kunt wegleggen en morgen verder kunt.
      if (!db.objectStoreNames.contains("wachtrij"))
        db.createObjectStore("wachtrij", { keyPath: "id" });
    };
    v.onsuccess = () => klaar(v.result);
    v.onerror = () => fout(v.error);
  });
  return _db;
}

function tx(store, modus, werk) {
  return open().then(db => new Promise((klaar, fout) => {
    const t = db.transaction(store, modus);
    const r = werk(t.objectStore(store));
    t.oncomplete = () => klaar(r && r.result !== undefined ? r.result : r);
    t.onerror = () => fout(t.error);
    t.onabort = () => fout(t.error);
  }));
}

/* ------------------------------------------------------------------ lezen -- */

export async function laad() {
  const platen = await tx("collectie", "readonly", s => s.getAll());
  const eigen = await tx("eigen", "readonly", s => s.getAll());
  const meta = await tx("meta", "readonly", s => s.get("doc"));

  const perId = new Map(eigen.map(e => [e.id, e]));
  const samen = platen.map(p => ({ ...p, eigen: perId.get(p.id) || {} }));
  samen.sort((a, b) =>
    (a.artiest || "~").localeCompare(b.artiest || "~", "nl") ||
    (a.titel || "").localeCompare(b.titel || "", "nl"));

  return {
    platen: samen,
    handmatig: (meta && meta.waarde && meta.waarde.handmatig) || [],
    naam: (meta && meta.waarde && meta.waarde.naam) || "Mijn platenkast",
    bijgewerkt: (meta && meta.waarde && meta.waarde.bijgewerkt) || null,
    basis: (meta && meta.waarde && meta.waarde.basis) || "",
    gebouwd: (meta && meta.waarde && meta.waarde.gebouwd) || "",
  };
}

export async function isGevuld() {
  const n = await tx("collectie", "readonly", s => s.count());
  return n > 0;
}

/* --------------------------------------------------------------- schrijven -- */

/* Elk record draagt een `gewijzigd`, en dat is er voor het synchroniseren.
 *
 * Een tijdstempel uit `toISOString()`: UTC, met milliseconden. Zo mag je ze als
 * TEKST vergelijken - ISO 8601 in UTC sorteert gelijk aan de tijd zelf - en dat
 * doen de server en deze kant allebei. Milliseconden en niet seconden, want
 * twee keer iets intikken binnen een seconde is doodnormaal en de tweede
 * wijziging hoort dan niet als "niet nieuwer" te sneuvelen.
 *
 * Staat er al een stempel op (een record uit een bestand of van de server), dan
 * blijft die staan. Anders zou binnenhalen hetzelfde zijn als wijzigen. */
const stempel = () => new Date().toISOString();

/** Vervangt de uitgerekende laag. `eigen` blijft onaangeroerd. */
export async function zetCollectie(doc, basis = "") {
  const platen = doc.platen || [];
  const nu = stempel();
  await tx("collectie", "readwrite", s => {
    s.clear();
    platen.forEach(p => s.put({ gewijzigd: nu, ...p }));
  });
  await tx("meta", "readwrite", s => s.put({
    sleutel: "doc",
    waarde: {
      naam: doc.naam || "Mijn platenkast",
      handmatig: doc.handmatig || [],
      bijgewerkt: new Date().toISOString(),
      gebouwd: doc.gebouwd || "",
      basis,
    },
  }));
  return platen.length;
}

/** Voegt platen toe zonder de rest weg te gooien - voor een tweede stapel. */
export async function vulAan(doc) {
  const platen = doc.platen || [];
  const nu = stempel();
  await tx("collectie", "readwrite", s => platen.forEach(p => s.put({ gewijzigd: nu, ...p })));
  return platen.length;
}

export async function zetEigen(id, velden) {
  const nu = await tx("eigen", "readonly", s => s.get(id));
  const nieuw = { ...(nu || { id }), ...velden, id };
  // een leeg veld hoort weg te gaan, niet als lege string te blijven staan
  Object.keys(nieuw).forEach(k => {
    if (nieuw[k] === "" || nieuw[k] === null || nieuw[k] === undefined) delete nieuw[k];
  });
  nieuw.id = id;
  nieuw.gewijzigd = stempel();       // NA het opschonen: dit veld hoort er altijd op
  await tx("eigen", "readwrite", s => s.put(nieuw));
  return nieuw;
}

export async function wisAlles() {
  await tx("collectie", "readwrite", s => s.clear());
  await tx("eigen", "readwrite", s => s.clear());
  await tx("meta", "readwrite", s => s.clear());
}

/* -------------------------------------------------------------- wachtrij -- */

/* Een plaat die nog verwerkt moet worden:
 *
 *   { id, gemaakt, staat, fotos: [{naam, blob}], plaat, reden, hoezen }
 *
 * `staat` is "wacht" | "bezig" | "klaar" | "mislukt". Hij staat in het record
 * en niet in het geheugen van het scherm, want anders is een plaat die stond
 * te verwerken toen je het tabblad sloot voor altijd "bezig".
 *
 * De id is een tijdstempel plus toeval, en die verandert nooit meer. Dat is
 * met het oog op straks: zodra hier een account achter komt te staan is dit de
 * sleutel waarop twee apparaten elkaar kunnen vinden, en een id die van de
 * inhoud of van de volgorde afhangt kan dat niet.
 */

export function nieuweId() {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

export async function zetInWachtrij(fotos, velden = {}) {
  const rij = {
    id: velden.id || nieuweId(),
    gemaakt: new Date().toISOString(),
    staat: "wacht",
    fotos,                                  // [{naam, blob}], voorkant eerst
    ...velden,
  };
  await tx("wachtrij", "readwrite", s => s.put(rij));
  return rij;
}

export async function wachtrij() {
  const alles = await tx("wachtrij", "readonly", s => s.getAll());
  return alles.sort((a, b) => (a.gemaakt || "").localeCompare(b.gemaakt || ""));
}

export async function wijzig(id, velden) {
  const nu = await tx("wachtrij", "readonly", s => s.get(id));
  if (!nu) return null;
  const nieuw = { ...nu, ...velden };
  await tx("wachtrij", "readwrite", s => s.put(nieuw));
  return nieuw;
}

export async function uitWachtrij(id) {
  await tx("wachtrij", "readwrite", s => s.delete(id));
}

/** Alles wat "bezig" stond terugzetten naar "wacht".
 *
 *  Draait bij het openen van het scherm. Een plaat kan alleen "bezig" zijn
 *  zolang er een motor loopt, en die loopt niet meer als de pagina opnieuw
 *  geladen is - dus dit is geen herstel maar een correctie van een leugen. */
export async function hervat() {
  const rijen = await wachtrij();
  const vast = rijen.filter(r => r.staat === "bezig");
  for (const r of vast) await wijzig(r.id, { staat: "wacht" });
  return vast.length;
}

/* ---------------------------------------------------------- synchroniseren -- */

/* Deze drie functies weten NIETS van HTTP - dat staat in sync.js. Hier staat
 * alleen wat er lokaal in en uit moet, want dat is het deel dat je fout kunt
 * doen op een manier die je pas maanden later merkt. */

/** De naam van de kast, met wanneer hij voor het laatst veranderde. */
export async function kastNaam() {
  const m = await tx("meta", "readonly", s => s.get("doc"));
  const w = (m && m.waarde) || {};
  return { naam: w.naam || "", gewijzigd: w.bijgewerkt || stempel() };
}

export async function syncStand() {
  const r = await tx("meta", "readonly", s => s.get("sync"));
  return (r && r.waarde) || { basis: "", gebruiker: null, laatst: "" };
}

export async function zetSyncStand(velden) {
  const nu = await syncStand();
  const waarde = { ...nu, ...velden };
  await tx("meta", "readwrite", s => s.put({ sleutel: "sync", waarde }));
  return waarde;
}

/** Alles wat hier veranderde sinds de vorige keer.
 *
 *  Records zonder stempel gaan MEE, met de tijd van nu. Dat is de kast zoals
 *  hij was voordat dit bestand stempels kende: die gegevens zijn echt en horen
 *  omhoog, niet overschreven te worden door een lege server. */
export async function teDuwen(sinds = "") {
  const nu = stempel();
  const pak = rijen => rijen
    .filter(r => (r.gewijzigd || nu) > sinds)
    .map(({ gewijzigd, ...doc }) => ({ id: doc.id, gewijzigd: gewijzigd || nu, doc }));
  return {
    platen: pak(await tx("collectie", "readonly", s => s.getAll())),
    eigen: pak(await tx("eigen", "readonly", s => s.getAll())),
  };
}

/** Wat de server terugstuurt hier binnenzetten.
 *
 *  Dezelfde regel als aan de serverkant, en met opzet ook HIER: tussen het
 *  moment dat we duwden en het moment dat het antwoord binnenkomt kun je
 *  gewoon iets ingetikt hebben. Klakkeloos overnemen zou dat wissen. */
export async function neemOver(antwoord) {
  const tel = { platen: 0, eigen: 0, behouden: 0, verwijderd: 0 };

  for (const [naam, winkel] of [["platen", "collectie"], ["eigen", "eigen"]]) {
    for (const r of antwoord[naam] || []) {
      const hier = await tx(winkel, "readonly", s => s.get(r.id));
      if (hier && (hier.gewijzigd || "") > r.gewijzigd) {
        tel.behouden++;                 // wat hier staat is nieuwer
        continue;
      }
      if (r.weg) {
        if (hier) tel.verwijderd++;
        await tx(winkel, "readwrite", s => s.delete(r.id));
        continue;
      }
      await tx(winkel, "readwrite",
               s => s.put({ ...r.doc, id: r.id, gewijzigd: r.gewijzigd }));
      tel[naam]++;
    }
  }

  if (antwoord.naam) {
    const m = await tx("meta", "readonly", s => s.get("doc"));
    const w = (m && m.waarde) || {};
    await tx("meta", "readwrite",
             s => s.put({ sleutel: "doc", waarde: { ...w, naam: antwoord.naam } }));
  }
  return tel;
}

/* ------------------------------------------------------- mee kunnen nemen -- */

/** Alles in één bestand, inclusief je eigen aantekeningen. Dit is voorlopig
 *  ook de enige manier om je kast op een tweede apparaat te krijgen. */
export async function exporteer() {
  const d = await laad();
  return {
    versie: 1,
    naam: d.naam,
    geexporteerd: new Date().toISOString(),
    platen: d.platen.map(({ eigen, ...p }) => ({ ...p, eigen })),
    handmatig: d.handmatig,
  };
}

export async function importeer(doc) {
  const schoon = (doc.platen || []).map(({ eigen, ...p }) => p);
  await zetCollectie({ ...doc, platen: schoon }, doc.basis || "");
  const eigen = (doc.platen || [])
    .filter(p => p.eigen && Object.keys(p.eigen).length)
    .map(p => ({ ...p.eigen, id: p.id }));
  if (eigen.length)
    await tx("eigen", "readwrite", s => eigen.forEach(e => s.put(e)));
  return schoon.length;
}
