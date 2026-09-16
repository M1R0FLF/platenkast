/* handmatig.js - de platen die de machine niet rond kreeg.
 *
 * Die horen apart te staan, niet verstopt onderaan een overzicht. Het zijn er
 * weinig (vier van de honderd) maar het is het enige werk dat echt op jou
 * wacht, en zonder hun hoesfoto ernaast is het onbegonnen werk.
 *
 * Waarom ze overbleven is telkens hetzelfde: een achterkant zonder tracklist.
 * Bij "A-tom-ic Jones" staat een verhaal over Tom Jones, bij de Bach-plaat de
 * bezetting van het orkest, en bij Streisand een advertentie voor zes andere
 * albums - compleet met catalogusnummers die beter aansluiten op de zoekopdracht
 * dan de plaat die je in handen hebt. Liever niets dan het verkeerde.
 *
 * Plak hier een Discogs-link en de motor haalt de rest op: persing, tracklist,
 * land, jaar en marktprijs. Dat is geen gok - jij wijst hem aan.
 */
import { el, toon, ICOON } from "./ui.js";
import * as opslag from "./opslag.js";

const MOTOR = "/api";

async function motorDraait() {
  try {
    const r = await fetch(`${MOTOR}/status`, { signal: AbortSignal.timeout(1200) });
    return r.ok;
  } catch {
    return false;
  }
}

function zoekterm(p) {
  const uit = (p.koptekst || []).slice(0, 2).join(" ") || p.titel || "";
  return encodeURIComponent(uit.trim());
}

function kaart(p, heeftMotor, klaarMelding) {
  const melding = el("p", { style: "font-size:12px;color:var(--zachter);margin:6px 0 0" });
  const invoer = el("input", {
    type: "text", placeholder: "plak hier de Discogs-link van deze plaat",
    style: "flex:1 1 240px",
  });

  const voorbeeld = el("div", { style: "margin-top:12px" });

  async function stuur(bevestigd) {
    const waarde = invoer.value.trim();
    if (!waarde) { melding.textContent = "Plak eerst een link of een release-nummer."; return; }
    vast.disabled = true;
    melding.textContent = bevestigd ? "bezig met vastleggen..." : "bezig met ophalen...";
    try {
      const r = await fetch(`${MOTOR}/handmatig`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ id: p.id, release: waarde, bevestigd }),
      });
      const b = await r.json();
      if (!r.ok) throw new Error(b.fout || `fout ${r.status}`);
      if (b.ok) {
        await opslag.zetCollectie(b.collectie, "handmatig aangevuld");
        melding.textContent = `vastgelegd als ${b.plaat.artist} - ${b.plaat.title}`;
        voorbeeld.replaceChildren();
        await klaarMelding();
        return;
      }
      toonVoorbeeld(b.voorbeeld);
      melding.textContent = "";
      vast.disabled = false;
    } catch (e) {
      melding.textContent = `niet gelukt: ${e.message}`;
      vast.disabled = false;
    }
  }

  /* Een link plakken is even makkelijk fout als goed - bij het testen werd een
   * verkeerd nummer klakkeloos "Gorillaz - Plastic Beach" onder een
   * Streisand-hoes. Daarom eerst laten zien wat je aanwijst, met de hoes van
   * Discogs naast de jouwe, en het oordeel van dezelfde beeldtoets die de rest
   * van de kast bewaakt. Beslissen doe jij. */
  function toonVoorbeeld(v) {
    const kloptNiet = v.hoes_klopt === false;
    const onbekend = v.hoes_klopt === null;
    voorbeeld.replaceChildren(el("div", {
      style: "display:flex;gap:12px;padding:12px;border-radius:8px;background:var(--pap);"
           + `border:1px solid ${kloptNiet ? "var(--fout)" : "var(--rand)"}`,
    }, [
      v.afbeelding
        ? el("img", { src: v.afbeelding, alt: "", referrerpolicy: "no-referrer",
                      style: "width:96px;height:96px;object-fit:cover;border-radius:6px;flex:none" })
        : null,
      el("div", { style: "flex:1;min-width:0" }, [
        el("div", { style: "font-weight:600", tekst: `${v.artiest || "?"} - ${v.titel || "?"}` }),
        el("div", { style: "font-size:12px;color:var(--zacht)",
                    tekst: [v.catno, v.land, v.jaar, v.formaat].filter(Boolean).join(" · ") }),
        el("div", {
          style: `font-size:12px;margin-top:6px;color:${
            kloptNiet ? "var(--fout)" : onbekend ? "var(--zachter)" : "var(--goed)"}`,
          tekst: kloptNiet
            ? `Let op: dit lijkt niet dezelfde hoes (${v.beeld_punten} punten). `
              + "Klopt het toch, leg het dan gewoon vast."
            : onbekend
              ? "Geen hoesafbeelding om mee te vergelijken."
              : `De hoes komt overeen (${v.beeld_punten} punten).`,
        }),
        el("div", { class: "veldrij", style: "margin-top:8px" }, [
          el("button", { class: "knop fel", tekst: "Ja, dit is hem",
                         onclick: () => stuur(true) }),
          el("button", { class: "knop", tekst: "Nee, andere link",
                         onclick: () => { voorbeeld.replaceChildren(); invoer.focus(); } }),
        ]),
      ]),
    ]));
  }

  const vast = el("button", { class: "knop fel", tekst: "Opzoeken",
                              onclick: () => stuur(false) });

  return el("section", { class: "kaart" }, [
    el("div", { style: "display:flex;gap:16px;flex-wrap:wrap" }, [
      el("div", { style: "display:flex;gap:8px;flex:none" },
        (p.duim || []).slice(0, 2).map(d =>
          el("img", { src: `publiek/duim/${d}`, loading: "lazy", alt: "",
                      style: "width:132px;height:132px;object-fit:cover;border-radius:8px" }))),
      el("div", { style: "flex:1;min-width:240px" }, [
        el("h3", { style: "margin:0 0 4px;text-transform:none;font-size:15px;color:var(--tekst)",
                   tekst: (p.koptekst || []).join(" · ") || `foto ${p.id}` }),
        el("p", { style: "margin:0 0 8px;font-size:12px;color:var(--zachter)",
                  tekst: p.reden || "niet herkend" }),
        (p.catno_kandidaten || []).length
          ? el("p", { style: "margin:0 0 8px;font-size:12px;color:var(--zacht)",
                      tekst: `nummers op de hoes: ${p.catno_kandidaten.join(", ")}` })
          : null,
        el("p", { style: "margin:0 0 10px" }, [
          el("a", { href: `https://www.discogs.com/search/?q=${zoekterm(p)}&type=release`,
                    target: "_blank", rel: "noopener",
                    tekst: "zoek deze plaat op Discogs ↗" }),
        ]),
        heeftMotor
          ? el("div", { class: "veldrij", style: "margin:0" }, [invoer, vast])
          : el("p", { style: "font-size:13px;color:var(--twijfel);margin:0",
              tekst: "Start de kast lokaal (Platenkast.bat, of py kast.py) om deze "
                   + "plaat alsnog vast te leggen - daar is de Discogs-verbinding." }),
        melding,
        voorbeeld,
      ]),
    ]),
  ]);
}

export async function scherm(data, herlaad) {
  const lijst = data.handmatig || [];
  if (!lijst.length) {
    return toon(el("div", { class: "leeg" }, [
      el("span", { html: ICOON.plaat, style: "display:block;width:40px;margin:0 auto 10px;color:var(--goed)" }),
      el("h2", { tekst: "Niets blijven liggen" }),
      el("p", { tekst: "Elke plaat is herkend en door de hoes bevestigd." }),
    ]));
  }

  const heeftMotor = await motorDraait();
  toon(el("div", {}, [
    el("p", { style: "color:var(--zacht);margin:0 0 16px" },
      [`${lijst.length} platen kwamen er niet doorheen. Dat is geen fout van de foto: `
     + `bij alle vier staat er te weinig op de achterkant om de persing te kunnen `
     + `bewijzen, en een verkeerde persing levert een verkeerde prijs op. `
     + `Wijs ze hier zelf aan.`]),
    ...lijst.map(p => kaart(p, heeftMotor, () => herlaad(true))),
  ]));
}
