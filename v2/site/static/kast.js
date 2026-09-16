/* kast.js - de kast zelf: raster, filters, en het paneel per plaat.
 *
 * Alles wat je hier intikt gaat naar de laag `eigen` en overleeft dus een
 * nieuwe run van de keten. Zie opslag.js.
 */
import { el, euro, kaal, wacht, toon, OORDEEL, SOORT, ICOON } from "./ui.js";
import * as opslag from "./opslag.js";

const STATUS = { kast: "in de kast", tekoop: "te koop", verkocht: "verkocht" };

let staat = { zoek: "", soort: "", oordeel: "", status: "", sorteer: "artiest" };
let alles = [];
let opnieuwTekenen = () => {};

/* ------------------------------------------------------------------ filter -- */

function past(p) {
  if (staat.soort && (p.soort || "LP") !== staat.soort) return false;
  if (staat.oordeel && p.oordeel !== staat.oordeel) return false;
  if (staat.status) {
    const s = p.eigen.status || "kast";
    if (s !== staat.status) return false;
  }
  if (!staat.zoek) return true;
  const n = kaal([
    p.artiest, p.titel, p.label, p.catno, p.land, p.jaar,
    (p.genres || []).join(" "),
    (p.tracks || []).map(t => t.titel).join(" "),
  ].join(" "));
  return staat.zoek.split(/\s+/).every(w => n.includes(w));
}

function prijsVan(p) {
  // je eigen prijs wint altijd van het advies: die heb je met de plaat in je
  // hand bepaald en het advies is een schatting op afstand
  const e = p.eigen.prijs;
  return e === undefined || e === null || e === "" ? p.prijs : +e;
}

const SORTEER = {
  artiest: (a, b) => (a.artiest || "~").localeCompare(b.artiest || "~", "nl"),
  prijs: (a, b) => (prijsVan(b) || 0) - (prijsVan(a) || 0),
  jaar: (a, b) => (b.jaar || 0) - (a.jaar || 0),
  toegevoegd: (a, b) => (b.id || "").localeCompare(a.id || ""),
};

/* ------------------------------------------------------------------ tegel -- */

function tegel(p) {
  const prijs = prijsVan(p);
  const status = p.eigen.status || "kast";
  const o = OORDEEL[p.oordeel] || OORDEEL.onbekend;
  const hoes = el("div", { class: "hoes" }, [
    p.duim && p.duim[0]
      ? el("img", { src: `publiek/duim/${p.duim[0]}`, loading: "lazy",
                    alt: `${p.artiest || ""} - ${p.titel || ""}` })
      : el("div", { class: "leeg", tekst: "geen foto" }),
    el("span", { class: `vlag v-${p.oordeel || "onbekend"}`,
                 title: `${o.tekst}: ${o.uitleg}` }),
    prijs ? el("span", { class: "prijs", tekst: euro(prijs) }) : null,
    status === "verkocht" ? el("span", { class: "verkocht", tekst: "verkocht" }) : null,
  ]);
  return el("button", { class: "plaat", onclick: () => paneel(p) }, [
    hoes,
    el("h4", { tekst: p.titel || "?" }),
    el("p", { tekst: p.artiest || "onbekend" }),
    el("p", { tekst: [SOORT[p.soort] || p.soort, p.jaar, p.land].filter(Boolean).join(" · ") }),
  ]);
}

/* ----------------------------------------------------------------- paneel -- */

function rij(naam, waarde) {
  if (!waarde && waarde !== 0) return null;
  return el("tr", {}, [el("td", { tekst: naam }),
                       el("td", {}, [waarde.nodeType ? waarde : String(waarde)])]);
}

function paneel(p) {
  const o = OORDEEL[p.oordeel] || OORDEEL.onbekend;
  const m = p.markt || {};
  const dlg = el("dialog", { class: "detail" });

  const bewaar = wacht(async velden => {
    p.eigen = await opslag.zetEigen(p.id, velden);
    opnieuwTekenen();
  }, 280);

  const veld = (naam, label, soort = "text", extra = {}) => {
    const huidig = p.eigen[naam] ?? "";
    const invoer = soort === "select"
      ? el("select", { onchange: e => bewaar({ [naam]: e.target.value }) },
          extra.opties.map(([w, t]) =>
            el("option", { value: w, selected: String(huidig || extra.standaard) === w, tekst: t })))
      : soort === "textarea"
        ? el("textarea", { rows: 3, oninput: e => bewaar({ [naam]: e.target.value }) }, [huidig])
        : el("input", { type: soort, value: huidig, ...extra,
                        oninput: e => bewaar({ [naam]: e.target.value }) });
    return el("div", { class: "veld" }, [el("label", { tekst: label }), invoer]);
  };

  const advertentie = p.advertentie && p.advertentie.tekst
    ? el("button", { class: "knop", onclick: e => {
        navigator.clipboard.writeText(
          `${p.advertentie.titel}\n\n${p.advertentie.tekst}`);
        e.target.textContent = "gekopieerd";
        setTimeout(() => (e.target.textContent = "advertentietekst kopieren"), 1400);
      }, tekst: "advertentietekst kopieren" })
    : null;

  dlg.append(el("div", { class: "rol" }, [
    el("div", { class: "beeld" },
      (p.duim || []).map(d => el("img", { src: `publiek/duim/${d}`, loading: "lazy", alt: "" }))),
    el("div", { class: "info" }, [
      el("h2", { tekst: p.titel || "?" }),
      el("p", { class: "sub", tekst: p.artiest || "onbekend" }),
      el("p", {}, [
        el("span", { class: `merkje ${o.klasse}`, title: o.uitleg, tekst: o.tekst }),
        " ",
        p.herkend_op ? el("span", { class: "merkje", tekst: `herkend op ${p.herkend_op}` }) : null,
      ]),
      el("table", { class: "feiten" }, [
        rij("Soort", SOORT[p.soort] || p.soort),
        rij("Label", p.label),
        rij("Catalogusnr", p.catno),
        rij("Persing", [p.land, p.jaar].filter(Boolean).join(", ")),
        rij("Formaat", p.formaat),
        rij("Genre", (p.genres || []).join(", ")),
        rij("Advies", p.advies),
        rij("Richtprijs", m.vgplus ? `${euro(m.vgplus)} (VG+ op Discogs)` : null),
        rij("Laagste nu", m.laagste ? `${euro(m.laagste)} van ${m.te_koop} te koop` : null),
        rij("Verzamelaars", m.have ? `${m.have} hebben hem, ${m.want} zoeken hem` : null),
        rij("Waarom", (p.oordeel_reden || []).join("; ")),
        // Het beeld is het enige bewijs dat NIET uit de OCR komt, dus dat hoort
        // zichtbaar te zijn. 399 punten en 41 punten zijn allebei "herkend",
        // maar het zijn niet dezelfde zekerheid.
        rij("Hoes vergeleken", p.beeld_punten === null || p.beeld_punten === undefined
          ? "geen hoesfoto op Discogs om mee te vergelijken"
          : `${p.beeld_punten} samenvallende punten`
            + (p.beeld_punten >= 100 ? " - dit is dezelfde hoes"
               : p.beeld_punten >= 30 ? " - waarschijnlijk dezelfde hoes, maar niet ruim"
               : " - zwak")),
        p.discogs ? rij("Discogs", el("a", { href: p.discogs, target: "_blank",
                                             rel: "noopener", tekst: "bekijk de persing" })) : null,
      ]),

      el("h3", { style: "font-size:13px;color:var(--zacht);margin:14px 0 4px",
                 tekst: "Van jou" }),
      el("div", { class: "veldrij" }, [
        veld("status", "Status", "select", {
          standaard: "kast",
          opties: Object.entries(STATUS).map(([w, t]) => [w, t]),
        }),
        veld("prijs", "Eigen prijs", "number", { step: "0.5", min: "0",
             placeholder: p.prijs ?? "" }),
      ]),
      el("div", { class: "veldrij" }, [
        veld("staat_hoes", "Staat hoes", "select", {
          standaard: "",
          opties: [["", "-"], ["M", "mint"], ["NM", "bijna mint"], ["VG+", "zeer goed +"],
                   ["VG", "zeer goed"], ["G", "redelijk"]],
        }),
        veld("staat_vinyl", "Staat vinyl", "select", {
          standaard: "",
          opties: [["", "-"], ["M", "mint"], ["NM", "bijna mint"], ["VG+", "zeer goed +"],
                   ["VG", "zeer goed"], ["G", "redelijk"]],
        }),
      ]),
      veld("notitie", "Notitie", "textarea"),

      (p.tracks || []).length
        ? el("details", { style: "margin-top:14px" }, [
            el("summary", { style: "cursor:pointer;color:var(--zacht)",
                            tekst: `Tracklist (${p.tracks.length})` }),
            el("ol", { style: "color:var(--zacht);font-size:13px" },
               p.tracks.map(t => el("li", { tekst: t.titel }))),
          ])
        : null,

      el("div", { class: "veldrij", style: "margin-top:16px" }, [
        advertentie,
        el("button", { class: "knop", onclick: () => dlg.close(), tekst: "sluiten" }),
      ]),
    ]),
  ]));

  document.body.append(dlg);
  dlg.addEventListener("close", () => dlg.remove());
  dlg.showModal();
}

/* ------------------------------------------------------------------ scherm -- */

export function scherm(data, hertekenKop) {
  alles = data.platen;

  const raster = el("div", { class: "raster" });
  const teller = el("p", { style: "color:var(--zachter);font-size:13px;margin:0 0 14px" });

  function teken() {
    const lijst = alles.filter(past).sort(SORTEER[staat.sorteer] || SORTEER.artiest);
    raster.replaceChildren(...lijst.map(tegel));
    const som = lijst.reduce((t, p) =>
      t + ((p.eigen.status || "kast") === "verkocht" ? 0 : (prijsVan(p) || 0)), 0);
    teller.textContent =
      `${lijst.length} van ${alles.length} platen${lijst.length !== alles.length ? " (gefilterd)" : ""}`
      + ` · samen ${euro(som)}`;
    if (!lijst.length)
      raster.replaceChildren(el("div", { class: "leeg" }, [
        el("h2", { tekst: "Niets gevonden" }),
        el("p", { tekst: "Andere zoekterm of zet de filters terug op alles." }),
      ]));
    if (hertekenKop) hertekenKop();
  }
  opnieuwTekenen = teken;

  const kies = (sleutel, opties) => el("select", {
    onchange: e => { staat[sleutel] = e.target.value; teken(); },
  }, opties.map(([w, t]) => el("option", { value: w, selected: staat[sleutel] === w, tekst: t })));

  toon(el("div", {}, [
    el("div", { class: "balk" }, [
      el("div", { class: "zoek" }, [
        el("span", { html: ICOON.zoek }),
        el("input", {
          type: "search", placeholder: "artiest, titel, label, nummer of een tracktitel",
          value: staat.zoek,
          oninput: wacht(e => { staat.zoek = kaal(e.target.value).trim(); teken(); }),
        }),
      ]),
      kies("soort", [["", "alle soorten"], ["LP", "LP"], ["single7", "single"],
                     ["maxi12", "maxi"], ["EP", "EP"]]),
      kies("status", [["", "alles"], ["kast", "in de kast"], ["tekoop", "te koop"],
                      ["verkocht", "verkocht"]]),
      kies("oordeel", [["", "elke zekerheid"], ["zeker", "zeker"],
                       ["aannemelijk", "aannemelijk"], ["onbevestigd", "onbevestigd"],
                       ["tegenspraak", "tegenspraak"]]),
      kies("sorteer", [["artiest", "op artiest"], ["prijs", "duurste eerst"],
                       ["jaar", "nieuwste eerst"], ["toegevoegd", "laatst toegevoegd"]]),
    ]),
    teller,
    raster,
  ]));
  teken();
}
