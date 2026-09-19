/* ui.js - de paar hulpjes die overal nodig zijn.
 * Geen framework: er staan hooguit een paar honderd tegels op het scherm en
 * dat kan het platte DOM prima aan. Wel innerHTML nergens met gegevens erin,
 * want een plaattitel is invoer en geen opmaak. */

export function el(soort, kenmerken = {}, kinderen = []) {
  const n = document.createElement(soort);
  for (const [k, v] of Object.entries(kenmerken)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") n.className = v;
    else if (k === "tekst") n.textContent = v;
    else if (k === "html") n.innerHTML = v;                 // alleen voor iconen
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v === true ? "" : v);
  }
  for (const kind of [].concat(kinderen)) {
    if (kind === null || kind === undefined || kind === false) continue;
    n.append(kind.nodeType ? kind : document.createTextNode(kind));
  }
  return n;
}

export const euro = n =>
  n === null || n === undefined || n === "" ? "-"
    : new Intl.NumberFormat("nl-NL", { style: "currency", currency: "EUR",
        maximumFractionDigits: Number.isInteger(+n) ? 0 : 2 }).format(n);

export const getal = n => new Intl.NumberFormat("nl-NL").format(n || 0);

export function wacht(fn, ms = 160) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

/** Zoeken zonder accenten en hoofdletters: wie "cafe" typt wil "Café" vinden. */
export const kaal = s => (s || "").toString().toLowerCase()
  .normalize("NFD").replace(/[̀-ͯ]/g, "");

export const OORDEEL = {
  zeker: { tekst: "zeker", klasse: "goed", uitleg: "het catalogusnummer staat op de hoes en geen andere persing draagt dat nummer" },
  // Het nummer is wel gelezen, maar het legt de UITGAVE vast en niet de
  // PERSING: labels nummerden per uitgave, niet per fabriek, dus dezelfde hoes
  // met hetzelfde nummer bestaat in twee landen. Nagemeten gold dat voor 44 van
  // de 77 platen die eerst "zeker" heetten. Sterker bewijs dan "aannemelijk",
  // zwakker dan "zeker", en dus een eigen stempel in plaats van een van die
  // twee die dan zou liegen.
  uitgave: { tekst: "uitgave", klasse: "uitgave", uitleg: "het catalogusnummer staat op de hoes, maar meer persingen delen dat nummer - de uitgave staat vast, de persing niet" },
  aannemelijk: { tekst: "aannemelijk", klasse: "twijfel", uitleg: "titel, artiest of de hoes zelf klopt en niets spreekt het tegen" },
  onbevestigd: { tekst: "onbevestigd", klasse: "", uitleg: "geen leesbare tekst en geen hoesfoto op Discogs om mee te vergelijken" },
  // Eigen niveau, en met opzet niet "zeker". Zeker betekent hier: de machine
  // heeft het catalogusnummer op de hoes GELEZEN. Bij een plaat uit je Discogs-
  // collectie is dat niet gebeurd - die heb jij daar zelf aangewezen, wat
  // meestal beter is, maar het is een ander soort zekerheid. Ze op een hoop
  // gooien maakt het stempel betekenisloos.
  overgenomen: { tekst: "overgenomen", klasse: "goed", uitleg: "uit jouw Discogs-collectie; door jou gekozen, niet door de machine gelezen" },
  tegenspraak: { tekst: "tegenspraak", klasse: "fout", uitleg: "de hoes zegt iets anders dan de gekozen persing" },
  onbekend: { tekst: "onbekend", klasse: "", uitleg: "niet beoordeeld" },
};

export const SOORT = { LP: "LP", single7: "single", maxi12: "maxi", EP: "EP" };

export function toon(knoop) {
  const m = document.querySelector("main");
  m.replaceChildren(knoop);
  m.scrollTop = 0;
}

/** Een staafje in een verdeling. Puur om te vergelijken, dus de schaal is
 *  relatief aan de grootste - absolute aantallen staan er los naast. */
export function staaf(naam, n, max, achtervoegsel = "") {
  return el("div", { class: "staaf" }, [
    el("span", { class: "naam", tekst: naam }),
    el("span", { class: "spoor" }, [
      el("i", { style: `width:${max ? Math.max(2, (n / max) * 100) : 0}%` }),
    ]),
    el("span", { class: "n", tekst: getal(n) + achtervoegsel }),
  ]);
}

export const ICOON = {
  zoek: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>',
  plaat: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="12" cy="12" r="9.2"/><circle cx="12" cy="12" r="3.1"/><circle cx="12" cy="12" r="0.7" fill="currentColor"/></svg>',
};
