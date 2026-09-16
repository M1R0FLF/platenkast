/* verwerk.js - foto's erin, platen eruit, terwijl je kijkt.
 *
 * Het rekenwerk gebeurt NIET hier. Het uitsnijden en de OCR kosten samen zo'n
 * negen seconden per foto en dat is werk voor een echte machine, niet voor een
 * webserver die per aanroep afrekent. Dit scherm praat met `kast.py`, dat op je
 * eigen computer draait en zijn voortgang doorgeeft via een event-stream.
 *
 * Staat die niet aan, dan is dit scherm de uitleg hoe je hem start. Dat is geen
 * foutmelding: op de gepubliceerde site is dat de normale toestand.
 */
import { el, euro, getal, toon } from "./ui.js";
import * as opslag from "./opslag.js";

const MOTOR = "/api";

async function motorStatus() {
  try {
    const r = await fetch(`${MOTOR}/status`, { signal: AbortSignal.timeout(1200) });
    return r.ok ? await r.json() : null;
  } catch {
    return null;                       // geen lokale motor, en dat mag
  }
}

/* ------------------------------------------------------------------ uitleg -- */

function opdracht(tekst) {
  return el("div", {
    style: "display:flex;gap:8px;align-items:center;background:var(--pap);"
         + "border:1px solid var(--rand);border-radius:8px;padding:9px 12px;margin:8px 0",
  }, [
    el("code", { style: "flex:1;font-size:13px;color:var(--tekst)", tekst }),
    el("button", {
      class: "knop", style: "padding:4px 9px;font-size:12px",
      onclick: e => {
        navigator.clipboard.writeText(tekst);
        e.target.textContent = "gekopieerd";
        setTimeout(() => (e.target.textContent = "kopieer"), 1300);
      },
      tekst: "kopieer",
    }),
  ]);
}

function geenMotor() {
  return el("div", {}, [
    el("section", { class: "kaart" }, [
      el("h3", { tekst: "Het verwerken draait op je eigen computer" }),
      el("p", { style: "color:var(--zacht);margin-top:0" },
        ["Een hoes uitsnijden en lezen kost ongeveer negen seconden. Voor "
       + "tweehonderd foto's is dat een half uur rekenwerk - te veel voor een "
       + "website, en je foto's hoeven er ook helemaal niet heen. Start de motor "
       + "in de map van het project:"]),
      opdracht("py kast.py"),
      el("p", { style: "color:var(--zacht)" },
        ["Die opent dit scherm opnieuw, maar dan met een knop om te beginnen. "
       + "Je hebt Python nodig en eenmalig:"]),
      opdracht("pip install -r vereisten.txt"),
      el("p", { style: "color:var(--zachter);font-size:13px" },
        ["Voor prijzen is een gratis Discogs-token nodig: discogs.com > Settings "
       + "> Developers > Generate token. Daarna eenmalig, in PowerShell:"]),
      opdracht('[Environment]::SetEnvironmentVariable("DISCOGS_TOKEN","jouw-token","User")'),
    ]),
    el("section", { class: "kaart" }, [
      el("h3", { tekst: "Al een kast ergens anders?" }),
      el("p", { style: "color:var(--zacht);margin-top:0",
        tekst: "Sla hem daar op als bestand en laad hem hier via het menu rechtsboven." }),
    ]),
  ]);
}

/* -------------------------------------------------------------------- run -- */

/** Naar de gepubliceerde site duwen.
 *
 *  Er is geen server die je kast ontvangt - dat was de afspraak: geen account,
 *  geen kosten, je foto's blijven van jou. Wat er wel is: dit project staat in
 *  git en Vercel bouwt bij elke push opnieuw. Dus "uploaden" is hier gewoon
 *  site/publiek committen en pushen, en een minuut later staat het erop.
 *
 *  Met opzet een knop en geen automatische stap na elke run: publiceren zet je
 *  platen en je foto's openbaar, en dat hoort een besluit te zijn.
 */
function publiceerknop(schrijf) {
  const uitleg = el("span", { style: "color:var(--zachter);font-size:12px" });
  const knop = el("button", {
    class: "knop", tekst: "Publiceer naar de website",
    onclick: async e => {
      if (!confirm("De kast zoals hij nu is naar de website zetten?\n\n"
                 + "Je platen, prijzen en hoesfoto's worden daarmee openbaar.")) return;
      e.target.disabled = true;
      uitleg.textContent = "bezig...";
      try {
        const r = await fetch(`${MOTOR}/publiceer`, { method: "POST" });
        const b = await r.json();
        uitleg.textContent = b.ok ? b.bericht : `mislukt: ${b.fout}`;
        if (!b.ok) schrijf(`publiceren mislukt: ${b.fout}`, "nee");
      } catch (err) {
        uitleg.textContent = `mislukt: ${err.message}`;
      } finally {
        e.target.disabled = false;
      }
    },
  });
  return el("div", { class: "veldrij", style: "margin-top:14px;align-items:center" },
            [knop, uitleg]);
}

function scherm_motor(status, herlaad) {
  const balk = el("i");
  const teller = {
    foto: el("b", { tekst: "0" }), plaat: el("b", { tekst: "0" }),
    waarde: el("b", { tekst: euro(0) }), zeker: el("b", { tekst: "0" }),
  };
  const log = el("div", { class: "log" });
  const stand = el("p", { style: "color:var(--zacht);margin:10px 0 0", tekst: "Nog niet begonnen." });
  let bezig = false, gestopt = false;

  const schrijf = (tekst, klasse = "") => {
    const onder = log.scrollTop + log.clientHeight >= log.scrollHeight - 30;
    log.append(el("div", { class: klasse, tekst }));
    if (onder) log.scrollTop = log.scrollHeight;
  };

  const start = el("button", { class: "knop fel", tekst: "Beginnen" });
  const stop = el("button", { class: "knop", disabled: true, tekst: "Stoppen" });
  const map = el("input", {
    type: "text", value: status.fotomap || "",
    placeholder: "volledig pad naar je map met foto's",
    style: "flex:1 1 320px",
  });

  // Een pad overtypen uit de verkenner was de onvriendelijkste stap die er
  // was. De browser mag ons geen pad geven, maar de motor draait op deze
  // machine en mag Windows wel om een mapkiezer vragen.
  const kiezer = el("button", {
    class: "knop", tekst: "Map kiezen...",
    onclick: async e => {
      e.target.disabled = true;
      try {
        const r = await fetch(`${MOTOR}/kies-map`, { method: "POST" });
        const b = await r.json();
        if (b.map) map.value = b.map;
        else if (b.fout) schrijf(`mapkiezer werkte niet (${b.fout}) - typ het pad`, "nee");
      } catch (err) {
        schrijf(`mapkiezer niet bereikbaar: ${err.message}`, "nee");
      } finally {
        e.target.disabled = false;
      }
    },
  });

  let gevonden = 0, waarde = 0, zeker = 0;

  stop.addEventListener("click", () => { gestopt = true; fetch(`${MOTOR}/stop`, { method: "POST" }); });

  start.addEventListener("click", async () => {
    if (bezig) return;
    bezig = true; gestopt = false;
    gevonden = 0; waarde = 0; zeker = 0;
    start.disabled = true; stop.disabled = false;
    log.replaceChildren();
    balk.style.width = "0%";
    stand.textContent = "Bezig met starten...";

    let bron;
    try {
      const r = await fetch(`${MOTOR}/start`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ map: map.value.trim() }),
      });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).fout || `fout ${r.status}`);
    } catch (e) {
      schrijf(`kan niet starten: ${e.message}`, "nee");
      stand.textContent = "Niet gestart.";
      bezig = false; start.disabled = false; stop.disabled = true;
      return;
    }

    const FASE = {
      lezen: "foto's uitsnijden en lezen",
      prijzen: "persing en prijs opzoeken",
      samenstellen: "kast samenstellen",
    };
    let fase = "lezen";

    bron = new EventSource(`${MOTOR}/stroom`);
    bron.onmessage = async ev => {
      const b = JSON.parse(ev.data);
      if (b.soort === "start") {
        schrijf(`${b.totaal} foto's in ${b.map}`);
      } else if (b.soort === "fase") {
        fase = b.naam;
        balk.style.width = "0%";
        stand.textContent = `${FASE[b.naam] || b.naam}...`;
        schrijf(`— ${FASE[b.naam] || b.naam} —`);
      } else if (b.soort === "voortgang") {
        teller.foto.textContent = getal(b.klaar);
        balk.style.width = `${(100 * b.klaar) / Math.max(b.totaal, 1)}%`;
        stand.textContent = `${b.klaar} van ${b.totaal} foto's gelezen`
          + (b.resterend ? ` — nog ongeveer ${b.resterend}` : "");
      } else if (b.soort === "herkend") {
        teller.plaat.textContent = getal(++gevonden);
        schrijf(`${b.artiest || "?"} — ${b.titel || "?"}`, "ok");
      } else if (b.soort === "bekend") {
        // stond al in de kast: geen werk, maar wel een plaat
        teller.plaat.textContent = getal(++gevonden);
      } else if (b.soort === "prijs") {
        waarde = b.waarde || waarde;
        if (b.prijs) zeker++;
        teller.waarde.textContent = euro(waarde);
        teller.zeker.textContent = getal(zeker);
        balk.style.width = `${(100 * b.klaar) / Math.max(b.totaal, 1)}%`;
        stand.textContent = `${b.klaar} van ${b.totaal} opgezocht`
          + (b.resterend ? ` — nog ongeveer ${b.resterend}` : "");
      } else if (b.soort === "onherkend") {
        schrijf(`niet herkend: ${b.id} — ${b.reden || "geen match"}`, "nee");
      } else if (b.soort === "melding") {
        schrijf(b.tekst);
      } else if (b.soort === "fout") {
        schrijf(b.bericht, "nee");
      } else if (b.soort === "klaar") {
        bron.close();
        bezig = false; start.disabled = false; stop.disabled = true;
        balk.style.width = "100%";
        stand.textContent = gestopt ? "Gestopt." : "Klaar.";
        schrijf(`klaar: ${b.platen} platen, samen ${euro(b.waarde || 0)}`);
        try {
          const r = await fetch(`${MOTOR}/collectie`);
          const doc = await r.json();
          await opslag.vulAan(doc);
          await herlaad(false);        // kop bijwerken, dit scherm laten staan
          schrijf(`${doc.platen.length} platen staan nu in je kast`, "ok");
        } catch (e) {
          schrijf(`resultaat kon niet opgeslagen worden: ${e.message}`, "nee");
        }
      }
    };
    bron.onerror = () => {
      if (!bezig) return;
      schrijf("verbinding met de motor verbroken", "nee");
      bron.close();
      bezig = false; start.disabled = false; stop.disabled = true;
    };
  });

  const cijfer = (knoop, label) =>
    el("div", { class: "kerncijfer" }, [knoop, el("span", { tekst: label })]);

  return el("div", {}, [
    el("section", { class: "kaart" }, [
      el("h3", { tekst: "Foto's verwerken" }),
      el("p", { style: "color:var(--zacht);margin-top:0",
        tekst: "Voorkant, dan achterkant, per plaat. Wat al eerder gelezen is "
             + "wordt overgeslagen, dus een tweede keer draaien is goedkoop." }),
      el("div", { class: "veldrij" }, [map, kiezer, start, stop]),
      el("div", { style: "margin:16px 0 6px" }, [el("div", { class: "voortgang" }, [balk])]),
      stand,
      status.token ? null : el("p", {
        style: "color:var(--twijfel);font-size:13px;margin:8px 0 0",
        tekst: "Geen DISCOGS_TOKEN gevonden: je krijgt geen prijzen en het gaat "
             + "ruim twee keer trager." }),
      status.kan_publiceren ? publiceerknop(schrijf) : null,
    ]),
    el("section", { class: "kaart" }, [
      el("div", { class: "kerncijfers", style: "margin-bottom:14px" }, [
        cijfer(teller.foto, "foto's gelezen"),
        cijfer(teller.plaat, "platen herkend"),
        cijfer(teller.zeker, "met een prijs"),
        cijfer(teller.waarde, "waarde tot nu toe"),
      ]),
      log,
    ]),
  ]);
}

export async function scherm(data, herlaad) {
  toon(el("div", {}, [el("p", { style: "color:var(--zachter)", tekst: "Kijken of de motor draait..." })]));
  const status = await motorStatus();
  toon(status ? scherm_motor(status, herlaad) : geenMotor());
}
