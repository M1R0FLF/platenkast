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

const TABS = [
  ["kast", "Kast"],
  ["verwerk", "Verwerken"],
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
  const zeker = p.filter(x => x.oordeel === "zeker" || x.oordeel === "aannemelijk").length;
  return el("div", { class: "kerncijfers" }, [
    el("div", { class: "kerncijfer" }, [
      el("b", { tekst: getal(p.length) }), el("span", { tekst: "platen" })]),
    el("div", { class: "kerncijfer" }, [
      el("b", { tekst: euro(waarde) }), el("span", { tekst: "geschatte waarde" })]),
    el("div", { class: "kerncijfer" }, [
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
        tekst: t,
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

herlaad();
