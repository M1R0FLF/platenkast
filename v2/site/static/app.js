/* app.js - de romp: kop, tabbladen, en de eerste keer vullen.
 *
 * De site bewaart jouw kast in je eigen browser (IndexedDB). Dat is met opzet:
 * zo is er geen account nodig, kost het niets, en blijven je foto's van jou.
 * De prijs ervan is dat een kast aan een apparaat vastzit, en daarom kan alles
 * met een knop naar een bestand en weer terug.
 */
import { el, euro, getal, toon, ICOON } from "./ui.js";
import * as opslag from "./opslag.js";
import * as kast from "./kast.js";
import * as overzicht from "./overzicht.js";
import * as verwerk from "./verwerk.js";
import * as handmatig from "./handmatig.js";

const TABS = [
  ["kast", "Kast"],
  ["verwerk", "Verwerken"],
  ["handmatig", "Nog te doen"],
  ["overzicht", "Overzicht"],
];

let data = { platen: [], handmatig: [], naam: "Mijn platenkast" };
let tab = location.hash.slice(1) || "kast";

/* --------------------------------------------------------------------- kop -- */

function kerncijfers() {
  const p = data.platen;
  const waarde = p.reduce((t, x) => {
    const e = x.eigen && x.eigen.prijs;
    return t + (e === undefined || e === null || e === "" ? (x.prijs || 0) : +e);
  }, 0);
  // Alleen ZEKER telt hier, en dat is geen slag om de arm maar de betekenis
  // van het woord: zeker is "het catalogusnummer van deze persing staat op de
  // hoes", en dat nummer is uniek per persing. Aannemelijk is een kloppende
  // titel of een kloppende hoes, en allebei zitten ze op elke persing van
  // dezelfde uitgave - die bevestigen de PLAAT, niet de persing. Ze meetellen
  // gaf 100% op een kop die "persing bevestigd" zegt, en dat is een belofte
  // die de gegevens niet waarmaken.
  const zeker = p.filter(x => x.oordeel === "zeker").length;
  const ook = p.filter(x => x.oordeel === "aannemelijk").length;
  return el("div", { class: "kerncijfers" }, [
    el("div", { class: "kerncijfer" }, [
      el("b", { tekst: getal(p.length) }), el("span", { tekst: "platen" })]),
    el("div", { class: "kerncijfer" }, [
      el("b", { tekst: euro(waarde) }), el("span", { tekst: "geschatte waarde" })]),
    el("div", { class: "kerncijfer",
                title: `${zeker} met het catalogusnummer op de hoes, `
                     + `${ook} aannemelijk (titel, artiest of hoes klopt)` }, [
      el("b", { tekst: p.length ? `${Math.round(100 * zeker / p.length)}%` : "-" }),
      el("span", { tekst: "persing bevestigd" })]),
  ]);
}

function kop() {
  const b = el("div", { class: "binnen" }, [
    el("div", { class: "merk" }, [
      el("span", { html: ICOON.plaat }),
      el("div", {}, [
        el("div", { tekst: data.naam }),
        el("small", { tekst: "van foto naar persing, prijs en kast" }),
      ]),
    ]),
    kerncijfers(),
    el("nav", { class: "tabs" }, TABS.map(([w, t]) =>
      el("button", {
        "aria-current": String(tab === w),
        onclick: () => ga(w),
        // het aantal in de tab zelf, anders zie je nooit dat er iets ligt
        tekst: w === "handmatig" && data.handmatig.length
          ? `${t} (${data.handmatig.length})` : t,
      }))),
    menu(),
  ]);
  document.querySelector("header.top").replaceChildren(b);
}

function menu() {
  return el("select", {
    style: "max-width:44px",
    onchange: async e => {
      const w = e.target.value;
      e.target.value = "";
      if (w === "uit") await bewaarBestand();
      if (w === "in") kiesBestand();
      if (w === "csv") await naarCsv();
      if (w === "wis" && confirm(
        "Alles uit deze browser wissen, inclusief je eigen prijzen en notities?\n"
        + "Dit kan niet ongedaan gemaakt worden. Exporteer eerst als je ze wilt houden.")) {
        await opslag.wisAlles();
        location.reload();
      }
    },
  }, [
    el("option", { value: "", tekst: "⋯" }),
    el("option", { value: "uit", tekst: "Kast opslaan als bestand" }),
    el("option", { value: "in", tekst: "Kast uit bestand laden" }),
    el("option", { value: "csv", tekst: "Verkooplijst als CSV" }),
    el("option", { value: "wis", tekst: "Alles wissen" }),
  ]);
}

/* ------------------------------------------------------------ in en uit -- */

function download(naam, inhoud, type) {
  const a = el("a", { href: URL.createObjectURL(new Blob([inhoud], { type })), download: naam });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 4000);
}

async function bewaarBestand() {
  const doc = await opslag.exporteer();
  download(`platenkast-${new Date().toISOString().slice(0, 10)}.json`,
           JSON.stringify(doc), "application/json");
}

function kiesBestand() {
  const invoer = el("input", { type: "file", accept: ".json,application/json" });
  invoer.addEventListener("change", async () => {
    const bestand = invoer.files[0];
    if (!bestand) return;
    try {
      const doc = JSON.parse(await bestand.text());
      if (!Array.isArray(doc.platen)) throw new Error("geen platen in dit bestand");
      const n = await opslag.importeer(doc);
      alert(`${n} platen geladen.`);
      await herlaad();
    } catch (e) {
      alert(`Dit bestand kon niet gelezen worden: ${e.message}`);
    }
  });
  invoer.click();
}

async function naarCsv() {
  const kolommen = ["artiest", "titel", "soort", "jaar", "label", "catalogusnummer",
                    "persing", "vraagprijs", "staat hoes", "staat vinyl", "status",
                    "notitie", "discogs"];
  const veld = v => {
    const s = v === null || v === undefined ? "" : String(v);
    return /[";\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const rijen = data.platen.map(p => [
    p.artiest, p.titel, p.soort, p.jaar, p.label, p.catno, p.land,
    p.eigen.prijs ?? p.prijs, p.eigen.staat_hoes, p.eigen.staat_vinyl,
    p.eigen.status || "kast", p.eigen.notitie, p.discogs,
  ].map(veld).join(";"));
  // BOM, want anders maakt Excel in Nederland er een kolom van
  download("verkooplijst.csv", "﻿" + [kolommen.join(";"), ...rijen].join("\r\n"),
           "text/csv;charset=utf-8");
}

/* -------------------------------------------------------------- eerste keer -- */

function welkom() {
  toon(el("div", { class: "leeg" }, [
    el("h2", { tekst: "Je kast is nog leeg" }),
    el("p", { tekst: "Laad de meegeleverde collectie om rond te kijken, of verwerk je eigen foto's." }),
    el("div", { class: "veldrij", style: "justify-content:center;max-width:420px;margin:18px auto" }, [
      el("button", { class: "knop fel", onclick: laadMeegeleverd, tekst: "Voorbeeldkast laden" }),
      el("button", { class: "knop", onclick: () => ga("verwerk"), tekst: "Eigen foto's verwerken" }),
      el("button", { class: "knop", onclick: kiesBestand, tekst: "Uit bestand" }),
    ]),
  ]));
}

async function laadMeegeleverd() {
  try {
    const r = await fetch("publiek/collectie.json");
    if (!r.ok) throw new Error(`${r.status}`);
    const doc = await r.json();
    await opslag.zetCollectie(doc, "meegeleverd");
    await herlaad();
  } catch (e) {
    alert(`De meegeleverde collectie kon niet geladen worden (${e.message}).`);
  }
}

/* De uitgerekende laag is wegwerpbaar; wat jij intikt staat in `eigen` en
 * blijft staan. Dus zodra de gepubliceerde collectie een ander stempel draagt
 * dan wat hier ligt, wordt de laag vervangen.
 *
 * Zonder dit haalde de site collectie.json precies EEN keer op - bij de eerste
 * klik op "Voorbeeldkast laden" - en daarna nooit meer. Miro keek dagenlang
 * naar de eerste versie die zijn browser ooit binnenkreeg: oude uitsnedes,
 * oude groepering, 614 euro en Met Liefde twee keer, terwijl de server allang
 * iets anders serveerde. Dat leek op verkeerd gedraaide hoezen en was het niet.
 *
 * Alleen voor een kast die van de site zelf komt. Heb je een eigen bestand
 * ingeladen, dan blijft dat van jou. */
const EIGEN_BASIS = ["meegeleverd", "handmatig aangevuld", ""];

async function ververs() {
  try {
    const d = await opslag.laad();
    if (!d.platen.length || !EIGEN_BASIS.includes(d.basis)) return false;
    const r = await fetch("publiek/collectie.json", { cache: "no-cache" });
    if (!r.ok) return false;
    const doc = await r.json();
    if (!doc.gebouwd || doc.gebouwd === d.gebouwd) return false;
    await opslag.zetCollectie(doc, "meegeleverd");
    return true;
  } catch (e) {
    return false;           // offline is geen reden om de kast te legen
  }
}

/* ------------------------------------------------------------------ router -- */

/** `hertekenScherm=false` ververst alleen de cijfers in de kop.
 *  Dat is wat het verwerkscherm nodig heeft als een run klaar is: de kast is
 *  bijgewerkt, maar het logboek en de tellers waar je naar zat te kijken
 *  moeten blijven staan. Hertekenen gooide ze weg op het moment dat ze
 *  eindelijk iets te vertellen hadden. */
export async function herlaad(hertekenScherm = true) {
  data = await opslag.laad();
  kop();
  if (hertekenScherm) teken();
}

function teken() {
  // een open plaatpaneel hoort niet over het volgende scherm heen te blijven
  // staan; van tabblad wisselen is ook "ik ben klaar met deze plaat"
  document.querySelectorAll("dialog[open]").forEach(d => d.close());
  if (!data.platen.length && tab !== "verwerk") return welkom();
  if (tab === "kast") kast.scherm(data, kop);
  else if (tab === "overzicht") overzicht.scherm(data);
  else if (tab === "handmatig") handmatig.scherm(data, herlaad);
  else verwerk.scherm(data, herlaad);
}

function ga(w) {
  tab = w;
  history.replaceState(null, "", `#${w}`);
  kop();
  teken();
}

window.addEventListener("hashchange", () => {
  const w = location.hash.slice(1) || "kast";
  if (w !== tab) ga(w);
});

herlaad().then(async () => {
  if (await ververs()) await herlaad();
});
