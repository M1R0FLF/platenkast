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
const VERSIE = 1;

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

/** Vervangt de uitgerekende laag. `eigen` blijft onaangeroerd. */
export async function zetCollectie(doc, basis = "") {
  const platen = doc.platen || [];
  await tx("collectie", "readwrite", s => {
    s.clear();
    platen.forEach(p => s.put(p));
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
  await tx("collectie", "readwrite", s => platen.forEach(p => s.put(p)));
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
  await tx("eigen", "readwrite", s => s.put(nieuw));
  return nieuw;
}

export async function wisAlles() {
  await tx("collectie", "readwrite", s => s.clear());
  await tx("eigen", "readwrite", s => s.clear());
  await tx("meta", "readwrite", s => s.clear());
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
