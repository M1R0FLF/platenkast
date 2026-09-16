/* overzicht.js - de samenvatting aan het eind: wat heb je, wat is het waard,
 * en wat verdient nog aandacht.
 *
 * Bewust geen taartdiagrammen. De vragen die je over een platenkast stelt zijn
 * "welke zijn het meest waard", "uit welk decennium komt dit allemaal" en
 * "welke moet ik nog nakijken" - dat zijn lijstjes en verdelingen, geen
 * verhoudingen van een geheel.
 */
import { el, euro, getal, staaf, toon, OORDEEL, SOORT } from "./ui.js";

const prijsVan = p => {
  const e = p.eigen && p.eigen.prijs;
  return e === undefined || e === null || e === "" ? p.prijs : +e;
};

function tel(lijst, sleutel) {
  const m = new Map();
  for (const p of lijst)
    for (const w of [].concat(sleutel(p)).filter(Boolean))
      m.set(w, (m.get(w) || 0) + 1);
  return [...m.entries()].sort((a, b) => b[1] - a[1]);
}

function kaart(titel, kinderen) {
  return el("section", { class: "kaart" }, [el("h3", { tekst: titel })].concat(kinderen));
}

export function scherm(data) {
  const platen = data.platen;
  const verkocht = platen.filter(p => (p.eigen.status || "kast") === "verkocht");
  const tekoop = platen.filter(p => (p.eigen.status || "kast") === "tekoop");
  const waarde = platen.reduce((t, p) => t + (prijsVan(p) || 0), 0);
  const opbrengst = verkocht.reduce((t, p) => t + (prijsVan(p) || 0), 0);
  const zonderPrijs = platen.filter(p => !prijsVan(p));

  /* ---- wat nog aandacht vraagt ---- */
  const aandacht = [
    ...platen.filter(p => p.oordeel === "tegenspraak")
      .map(p => [p, "de hoes spreekt de gekozen persing tegen"]),
    ...data.handmatig.map(h => [h, "niet herkend - zelf opzoeken"]),
    ...platen.filter(p => p.oordeel === "onbevestigd")
      .map(p => [p, "te weinig leesbare tekst om te toetsen"]),
  ];

  /* Een onherkende plaat heeft geen artiest en geen titel - dat is juist wat
   * er misging. Wel de grootst gedrukte regels van de voorkant, en daar
   * herken je hem aan. */
  const naam = p => p.artiest && p.titel ? `${p.artiest} - ${p.titel}`
    : p.titel || (p.koptekst || []).join(" · ") || p.id;

  const aandachtrij = ([p, waarom]) => el("div", {
    style: "display:flex;gap:11px;align-items:center;padding:7px 0;border-bottom:1px solid var(--rand)",
  }, [
    p.duim && p.duim[0]
      ? el("img", { src: `publiek/duim/${p.duim[0]}`, loading: "lazy", alt: "",
                    style: "width:40px;height:40px;object-fit:cover;border-radius:5px;flex:none" })
      : el("span", { style: "width:40px;height:40px;border-radius:5px;background:var(--rand);flex:none" }),
    el("div", { style: "flex:1;min-width:0" }, [
      el("div", { style: "font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap",
                  tekst: naam(p) }),
      el("div", { style: "font-size:12px;color:var(--zachter)",
                  tekst: (p.catno_kandidaten || []).length
                    ? `nummers op de hoes: ${p.catno_kandidaten.join(", ")}` : waarom }),
    ]),
    p.catno_kandidaten
      ? el("a", { href: `https://www.discogs.com/search/?q=${encodeURIComponent(
            (p.koptekst || [p.titel || ""]).slice(0, 2).join(" "))}&type=release`,
          target: "_blank", rel: "noopener",
          style: "font-size:12px;white-space:nowrap", tekst: "zoek op Discogs" })
      : el("span", { style: "font-size:12px;color:var(--zachter);white-space:nowrap", tekst: waarom }),
  ]);

  /* ---- verdelingen ---- */
  const decennia = tel(platen, p => p.jaar ? `${Math.floor(p.jaar / 10) * 10}s` : null)
    .sort((a, b) => a[0].localeCompare(b[0]));
  const genres = tel(platen, p => (p.genres || []).slice(0, 2)).slice(0, 8);
  const landen = tel(platen, p => p.land).slice(0, 6);
  const soorten = tel(platen, p => SOORT[p.soort] || p.soort || "LP");

  const duurste = [...platen].filter(p => prijsVan(p))
    .sort((a, b) => prijsVan(b) - prijsVan(a)).slice(0, 8);
  const gezocht = [...platen]
    .filter(p => p.markt && p.markt.want && p.markt.have)
    .map(p => [p, p.markt.want / Math.max(p.markt.have, 1)])
    .sort((a, b) => b[1] - a[1]).slice(0, 6);

  const maxD = Math.max(...decennia.map(d => d[1]), 1);
  const maxG = Math.max(...genres.map(d => d[1]), 1);
  const maxL = Math.max(...landen.map(d => d[1]), 1);

  const regel = (links, rechts) =>
    el("div", { style: "display:flex;justify-content:space-between;gap:12px;padding:5px 0;border-bottom:1px solid var(--rand);font-size:13px" },
      [el("span", { style: "overflow:hidden;text-overflow:ellipsis;white-space:nowrap", tekst: links }),
       el("span", { style: "color:var(--zacht);white-space:nowrap", tekst: rechts })]);

  toon(el("div", {}, [
    el("div", { class: "tweekolom" }, [
      kaart("De kast in het kort", [
        regel(`${getal(platen.length)} platen`, `${getal(soorten.length)} soorten`),
        regel("Geschatte waarde", euro(waarde)),
        regel("Te koop gezet", `${getal(tekoop.length)} · ${euro(tekoop.reduce((t, p) => t + (prijsVan(p) || 0), 0))}`),
        regel("Verkocht", `${getal(verkocht.length)} · ${euro(opbrengst)}`),
        regel("Nog geen prijs", `${getal(zonderPrijs.length)} platen`),
        data.bijgewerkt
          ? regel("Laatst bijgewerkt",
              new Date(data.bijgewerkt).toLocaleDateString("nl-NL",
                { day: "numeric", month: "long", year: "numeric" }))
          : null,
      ]),

      kaart("Hoe zeker is de persing", [
        ...["zeker", "aannemelijk", "onbevestigd", "tegenspraak"].map(k => {
          const n = platen.filter(p => p.oordeel === k).length;
          return staaf(OORDEEL[k].tekst, n, platen.length);
        }),
        el("p", { style: "color:var(--zachter);font-size:12px;margin:12px 0 0",
          tekst: "Zeker betekent dat het catalogusnummer van die persing letterlijk "
               + "op de hoes staat. Aannemelijk betekent dat de titel, de artiest of "
               + "de hoes zelf klopt - de hoes kan nooit zeker opleveren, want dezelfde "
               + "hoes zit op elke persing. Onbevestigd is niet fout: er was niets om "
               + "mee na te kijken." }),
      ]),
    ]),

    aandacht.length
      ? kaart(`Vraagt nog aandacht (${aandacht.length})`,
          aandacht.slice(0, 12).map(aandachtrij))
      : kaart("Vraagt nog aandacht", [
          el("p", { style: "color:var(--goed);margin:0", tekst: "Niets. Alles is herkend en niets spreekt elkaar tegen." })]),

    el("div", { class: "tweekolom" }, [
      kaart("Meest waard", duurste.map(p =>
        regel(`${p.artiest || "?"} - ${p.titel || "?"}`, euro(prijsVan(p))))),

      kaart("Het meest gezocht", gezocht.length
        ? gezocht.map(([p, r]) =>
            regel(`${p.artiest || "?"} - ${p.titel || "?"}`,
                  `${p.markt.want} zoekers op ${p.markt.have} bezitters`))
        : [el("p", { style: "color:var(--zachter);margin:0", tekst: "Nog geen marktdata." })]),
    ]),

    el("div", { class: "tweekolom" }, [
      kaart("Uit welk decennium", decennia.map(([d, n]) => staaf(d, n, maxD))),
      kaart("Genre", genres.map(([g, n]) => staaf(g, n, maxG))),
      kaart("Persland", landen.map(([l, n]) => staaf(l, n, maxL))),
      kaart("Soort", soorten.map(([s, n]) => staaf(s, n, Math.max(...soorten.map(x => x[1]), 1)))),
    ]),
  ]));
}
