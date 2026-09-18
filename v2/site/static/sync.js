/* sync.js - dezelfde kast op je telefoon en je pc.
 *
 * De kast staat in je browser (zie opslag.js) en dat blijft zo. Dit legt er een
 * kopie naast op een server die JIJ draait, zodat twee apparaten elkaar kunnen
 * vinden. Het is geen vervanging: valt de server weg, dan werkt de kast gewoon
 * door - hij synchroniseert alleen niet.
 *
 * De volgorde is duwen-dan-halen, en dat is niet willekeurig. Eerst duwen
 * betekent dat de server alles heeft voor hij antwoordt, dus wat er terugkomt
 * IS de uitkomst van het samenvoegen. Andersom zou je een ronde achterlopen en
 * dat pas merken als twee apparaten elkaar tegenspreken.
 *
 * Zie server/kastserver.py voor de andere helft, en server/LEESMIJ.md voor het
 * opzetten.
 */
import * as opslag from "./opslag.js";

/** Records per keer. Honderd platen is 172 KB, dus 500 is ruim onder een
 *  megabyte - klein genoeg voor een telefoon op 4G in een platenzaak. */
const BROK = 500;

export class Syncfout extends Error {}

async function vraag(basis, pad, lichaam) {
  let a;
  try {
    a = await fetch((basis || "") + pad, {
      method: lichaam === undefined ? "GET" : "POST",
      headers: lichaam === undefined ? {} : { "content-type": "application/json" },
      body: lichaam === undefined ? undefined : JSON.stringify(lichaam),
      // Zonder dit gaat het sessiekoekje niet mee naar een server op een ander
      // adres, en dan ben je bij elk verzoek weer een vreemde.
      credentials: "include",
      cache: "no-store",
    });
  } catch (e) {
    throw new Syncfout("de server is niet bereikbaar");
  }
  let doc = {};
  try {
    doc = await a.json();
  } catch (e) {
    throw new Syncfout(`de server antwoordde geen JSON (${a.status})`);
  }
  if (!a.ok) throw new Syncfout(doc.fout || `de server gaf ${a.status}`);
  return doc;
}

/* ------------------------------------------------------------------ waar -- */

/** Het adres van je server. Leeg = deze site WORDT er al door geserveerd.
 *
 *  Dat lege geval is de rustigste opstelling: zelfde herkomst, dus geen CORS,
 *  geen koekjes die van een ander domein moeten komen, niets. */
export async function server() {
  return (await opslag.syncStand()).basis || "";
}

export async function zetServer(url) {
  const schoon = (url || "").trim().replace(/\/+$/, "");
  if (schoon && !/^https?:\/\//.test(schoon))
    throw new Syncfout("een adres begint met http:// of https://");
  return opslag.zetSyncStand({ basis: schoon });
}

/* ---------------------------------------------------------------- wie ben -- */

export async function wie() {
  const basis = await server();
  try {
    const r = await vraag(basis, "/api/wie");
    return { server: true, ...r };
  } catch (e) {
    // Geen server is een normale toestand, geen storing: de meeste mensen
    // hebben er geen. Dus geen foutmelding, alleen "er is er geen".
    return { server: false, aangemeld: false, fout: e.message };
  }
}

export async function aanmelden(url, sleutel) {
  if (url !== undefined && url !== null) await zetServer(url);
  const basis = await server();
  const r = await vraag(basis, "/api/aanmelden", { sleutel: (sleutel || "").trim() });
  // De sleutel zelf bewaren we NERGENS. De server gaf een sessiekoekje terug en
  // dat is genoeg; een sleutel in localStorage is een sleutel die meegaat in
  // elke back-up en elke schermafdruk.
  await opslag.zetSyncStand({ gebruiker: r.gebruiker });
  return r;
}

export async function afmelden() {
  const basis = await server();
  try {
    await vraag(basis, "/api/afmelden", {});
  } finally {
    await opslag.zetSyncStand({ gebruiker: null, laatst: "" });
  }
}

/* ------------------------------------------------------------ het echte werk -- */

/**
 * Duwen, halen, binnenzetten. `opGang(tekst)` krijgt te horen waar hij is.
 *
 * Geeft een verslag terug met wat er heen en weer ging. Bewust getallen en geen
 * "gelukt": bij het synchroniseren is "er ging niets heen en weer" een heel
 * ander bericht dan "er gingen 40 platen omhoog", en allebei zijn ze goed.
 */
export async function synchroniseer(opGang = () => {}) {
  const basis = await server();
  const stand = await opslag.syncStand();
  const sinds = stand.laatst || "";

  opGang("kijken wat er veranderd is");
  const lokaal = await opslag.teDuwen(sinds);
  const totaal = lokaal.platen.length + lokaal.eigen.length;

  // De twee lagen krijgen hun EIGEN brokken. Ze samen opdelen op dezelfde
  // index gaat mis zodra ze niet even lang zijn, en dat zijn ze nooit.
  const brokken = [];
  for (let i = 0; i < lokaal.platen.length; i += BROK)
    brokken.push({ platen: lokaal.platen.slice(i, i + BROK), eigen: [] });
  for (let i = 0; i < lokaal.eigen.length; i += BROK)
    brokken.push({ platen: [], eigen: lokaal.eigen.slice(i, i + BROK) });
  if (!brokken.length) brokken.push({ platen: [], eigen: [] });

  // De naam van de kast reist mee met het eerste pakje, met zijn eigen stempel.
  const naam = await opslag.kastNaam();
  if (naam.naam) Object.assign(brokken[0], { naam: naam.naam, naam_gewijzigd: naam.gewijzigd });

  let omhoog = { platen: 0, eigen: 0 }, geweigerd = 0, gedaan = 0;
  for (const brok of brokken) {
    gedaan += brok.platen.length + brok.eigen.length;
    if (totaal) opGang(`versturen (${gedaan} van ${totaal})`);
    const r = await vraag(basis, "/api/duw", brok);
    omhoog.platen += r.platen.aangenomen;
    omhoog.eigen += r.eigen.aangenomen;
    geweigerd += r.platen.geweigerd + r.eigen.geweigerd;
  }

  opGang("ophalen");
  const antwoord = await vraag(
    basis, `/api/haal?sinds=${encodeURIComponent(sinds)}`);

  opGang("binnenzetten");
  const omlaag = await opslag.neemOver(antwoord);

  // Pas NU het merkteken verzetten, en op de tijd van de SERVER. Op de onze zou
  // een klok die voorloopt een venster overslaan waarin het andere apparaat
  // iets veranderde - en die wijziging zie je dan nooit meer.
  await opslag.zetSyncStand({ laatst: antwoord.nu });

  return {
    omhoog,
    omlaag,
    geweigerd,
    // "geweigerd" is meestal geen probleem: het is wat we terugduwden en wat de
    // server al kende. Alleen als het er veel zijn en er niets omhoog ging is
    // er iets raars aan de hand.
    tijd: antwoord.nu,
  };
}
