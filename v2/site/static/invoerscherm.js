/* invoerscherm.js - het scherm waar je je Discogs-collectie binnenhaalt.
 *
 * Twee wegen, en de eerste is met opzet de bovenste: een CSV-export vraagt geen
 * token, geen wachten op een snelheidslimiet, en er hoeft niets van jou naar
 * een sleutel te worden herleid. De API-weg is er voor wie hem toch wil, of
 * voor wie zijn collectie vaak bijwerkt.
 *
 * De uitleg staat hier op het scherm en niet in een handleiding, want dit is
 * precies het moment waarop iemand hem nodig heeft.
 */
import { el, toon } from "./ui.js";
import * as opslag from "./opslag.js";

const TOKEN_URL = "https://www.discogs.com/settings/developers";
const EXPORT_URL = "https://www.discogs.com/user/collection";

const token = () => {
  try { return localStorage.getItem("discogs_token") || ""; } catch { return ""; }
};

function stap(n, ...inhoud) {
  return el("li", { class: "stap" }, inhoud);
}

export async function scherm(herlaad) {
  const melding = el("p", { class: "invoermelding", style: "display:none" });
  const zeg = (tekst, klasse = "") => {
    melding.style.display = tekst ? "" : "none";
    melding.className = `invoermelding ${klasse}`;
    melding.textContent = tekst;
  };

  /* ---- weg 1: de export ---- */

  async function neemOver(platen, eigen, waarvandaan) {
    const bestaand = (await opslag.laad()).platen.length;
    if (!confirm(`${platen.length} platen gevonden in ${waarvandaan}.\n\n`
               + `Ze komen bij de ${bestaand} die je al hebt. Doorgaan?`)) return;
    await opslag.vulAan({ platen });
    for (const e of (eigen || [])) {
      const { id, ...rest } = e;
      await opslag.zetEigen(id, rest);
    }
    zeg(`${platen.length} platen staan in je kast.`, "goed");
    await herlaad(false);
  }

  const csvKnop = el("button", {
    class: "knop fel", tekst: "Export kiezen...",
    onclick: () => {
      const invoer = el("input", { type: "file", accept: ".csv,text/csv" });
      invoer.addEventListener("change", async () => {
        const f = invoer.files[0];
        if (!f) return;
        zeg(`${f.name} lezen...`);
        try {
          const { uitCsv } = await import("./invoer.js");
          const { platen, eigen } = uitCsv(await f.text());
          await neemOver(platen, eigen, f.name);
        } catch (e) {
          zeg(`Dit bestand kon niet gelezen worden: ${e.message}`, "fout");
        }
      });
      invoer.click();
    },
  });

  /* ---- weg 2: de API ---- */

  const tokenveld = el("input", {
    type: "password", value: token(), placeholder: "plak hier je token",
    style: "flex:1 1 240px", autocomplete: "off", spellcheck: "false",
  });

  const apiKnop = el("button", {
    class: "knop", tekst: "Ophalen",
    onclick: async e => {
      const t = tokenveld.value.trim();
      if (!t) return zeg("Er staat nog geen token in het veld.", "fout");
      try { localStorage.setItem("discogs_token", t); } catch {}
      e.target.disabled = true;
      try {
        const { haalCollectie } = await import("./invoer.js");
        const { naam, platen } = await haalCollectie(t, v =>
          zeg(`${v.naam || ""}: ${v.klaar} van de ${v.totaal} opgehaald...`));
        if (!platen.length) {
          zeg(`De collectie van ${naam} is leeg, of staat op prive. `
            + "Op Discogs staat je collectie standaard op prive - dat mag, "
            + "want jouw token mag hem wel zien.", "fout");
        } else {
          await neemOver(platen, null, `de collectie van ${naam}`);
        }
      } catch (err) {
        zeg(err.message, "fout");
      } finally {
        e.target.disabled = false;
      }
    },
  });

  /* ---- het scherm ---- */

  toon(el("div", {}, [
    el("section", { class: "kaart" }, [
      el("h3", { tekst: "Uit een export — zonder token" }),
      el("p", { class: "toelichting",
        tekst: "De snelste weg, en er komt geen sleutel aan te pas. In de "
             + "export staat per plaat het release-id, en daarmee ligt de "
             + "persing vast — niet alleen welke plaat het is, maar welke "
             + "uitgave. Dat is precies waar deze kast om draait." }),
      el("ol", { class: "stappen" }, [
        stap(1, "Ga op discogs.com naar ", el("a", {
          href: EXPORT_URL, target: "_blank", rel: "noopener",
          tekst: "je collectie" }), "."),
        stap(2, "Klik rechtsboven op ", el("b", { tekst: "Export" }),
                ", kies ", el("b", { tekst: "Collection" }), " en verstuur."),
        stap(3, "Discogs mailt je een link, of zet hem klaar onder Exports. "
              + "Download het CSV-bestand."),
        stap(4, "Kies dat bestand hieronder. Je staat en notities uit Discogs "
              + "komen mee."),
      ]),
      el("div", { class: "veldrij" }, [csvKnop]),
    ]),

    el("section", { class: "kaart" }, [
      el("h3", { tekst: "Rechtstreeks — met een token" }),
      el("p", { class: "toelichting",
        tekst: "Handig als je je collectie vaak bijwerkt: geen export, gewoon "
             + "ophalen. Je token blijft in deze browser staan en gaat nergens "
             + "anders heen." }),
      el("ol", { class: "stappen" }, [
        stap(1, "Ga naar ", el("a", {
          href: TOKEN_URL, target: "_blank", rel: "noopener",
          tekst: "discogs.com → Settings → Developers" }), "."),
        stap(2, "Klik op ", el("b", { tekst: "Generate new token" }),
                " (de knop onder ", el("i", { tekst: "Personal access token" }),
                "). Gratis."),
        stap(3, "Kopieer de reeks tekens en plak hem hieronder."),
      ]),
      el("div", { class: "veldrij" }, [tokenveld, apiKnop]),
      el("p", { class: "sleeptekst", style: "text-align:left",
        tekst: "Let op: zo'n token geeft toegang tot je Discogs-account — je "
             + "collectie, je bestellingen, je verkoperskant. Zet hem niet in "
             + "een e-mail, een chat of een openbare map. Hier blijft hij in "
             + "je browser." }),
    ]),

    el("section", { class: "kaart" }, [
      el("h3", { tekst: "Wat er wel en niet meekomt" }),
      el("p", { class: "toelichting",
        tekst: "Beide wegen leveren artiest, titel, label, catalogusnummer, "
             + "jaar en formaat. Land, tracklist en marktprijs staan er niet "
             + "in: die kosten een aanroep per plaat bij Discogs, en dat is "
             + "een aparte keuze — bij vijfhonderd platen een kwartier." }),
      el("p", { class: "toelichting",
        tekst: "Deze platen krijgen het stempel “overgenomen” en niet "
             + "“zeker”. Zeker betekent hier dat de machine het "
             + "catalogusnummer op de hoes heeft gelezen; bij een plaat uit "
             + "Discogs heb jij hem aangewezen. Meestal beter, maar een ander "
             + "soort zekerheid, en die twee door elkaar halen maakt het "
             + "stempel betekenisloos." }),
    ]),

    melding,
  ]));
}
