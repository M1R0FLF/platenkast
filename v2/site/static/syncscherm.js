/* syncscherm.js - je kast koppelen aan je eigen server.
 *
 * Lui geladen vanuit het menu: wie geen server heeft haalt deze code nooit op.
 *
 * Wat hier bewust NIET staat is een knop "maak een account". Een uitnodiging
 * maak je op de machine waar de server draait, met een opdracht op de
 * opdrachtregel. Dat is geen ruwe rand die nog afgewerkt moet worden: zolang
 * accounts zo ontstaan, is er geen enkel pad van buitenaf waarlangs iemand er
 * een kan maken, en hoeft er dus ook geen beheerderswachtwoord te bestaan dat
 * verkeerd kan gaan.
 */
import { el, toon } from "./ui.js";
import * as opslag from "./opslag.js";
import * as sync from "./sync.js";

const klok = t => {
  if (!t) return "nog nooit";
  const d = new Date(t);
  return isNaN(d) ? t : d.toLocaleString("nl-NL",
    { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
};

function stap(...inhoud) {
  return el("li", { class: "stap" }, inhoud);
}

export async function scherm(herlaad) {
  const melding = el("p", { class: "invoermelding", style: "display:none" });
  const zeg = (tekst, klasse = "") => {
    melding.style.display = tekst ? "" : "none";
    melding.className = `invoermelding ${klasse}`;
    melding.textContent = tekst;
  };

  const stand = await opslag.syncStand();
  const status = await sync.wie();

  /* ---------------------------------------------------------- aanmelden -- */

  const adresveld = el("input", {
    type: "url", placeholder: "https://kast.jouwadres.nl", value: stand.basis || "",
    style: "flex:1;min-width:220px",
  });
  const sleutelveld = el("input", {
    type: "password", placeholder: "je uitnodigingssleutel",
    autocomplete: "off", style: "flex:1;min-width:220px",
  });

  const aanmeldknop = el("button", {
    class: "knop fel", tekst: "Koppelen",
    onclick: async () => {
      aanmeldknop.disabled = true;
      zeg("koppelen...");
      try {
        await sync.aanmelden(adresveld.value, sleutelveld.value);
        sleutelveld.value = "";
        zeg("gekoppeld. Nu een eerste keer synchroniseren.", "goed");
        await scherm(herlaad);
      } catch (e) {
        zeg(e.message, "fout");
        aanmeldknop.disabled = false;
      }
    },
  });

  /* ------------------------------------------------------ synchroniseren -- */

  const syncknop = el("button", {
    class: "knop fel", tekst: "Nu synchroniseren",
    onclick: async () => {
      syncknop.disabled = true;
      try {
        const r = await sync.synchroniseer(t => zeg(t));
        const omhoog = r.omhoog.platen + r.omhoog.eigen;
        const omlaag = r.omlaag.platen + r.omlaag.eigen;
        const delen = [];
        if (omhoog) delen.push(`${omhoog} omhoog`);
        if (omlaag) delen.push(`${omlaag} omlaag`);
        if (r.omlaag.verwijderd) delen.push(`${r.omlaag.verwijderd} verwijderd`);
        if (r.omlaag.behouden) delen.push(`${r.omlaag.behouden} hier nieuwer, dus gehouden`);
        zeg(delen.length ? `Klaar: ${delen.join(", ")}.`
                         : "Klaar. Alles stond al gelijk.", "goed");
        await herlaad(false);
        await scherm(herlaad);
      } catch (e) {
        zeg(e.message, "fout");
      } finally {
        syncknop.disabled = false;
      }
    },
  });

  const afknop = el("button", {
    class: "knop", tekst: "Ontkoppelen",
    onclick: async () => {
      if (!confirm("Deze browser loskoppelen van de server?\n\n"
                 + "Je kast blijft hier gewoon staan - er gaat niets verloren. "
                 + "Je hebt je sleutel weer nodig om opnieuw te koppelen.")) return;
      await sync.afmelden();
      zeg("ontkoppeld.", "goed");
      await scherm(herlaad);
    },
  });

  /* ------------------------------------------------------------- scherm -- */

  const gekoppeld = status.aangemeld;

  toon(el("div", {}, [
    el("section", { class: "kaart" }, [
      el("h3", { tekst: gekoppeld ? "Gekoppeld" : "Koppelen aan je server" }),

      gekoppeld
        ? el("p", { class: "toelichting",
            tekst: `Deze browser hoort bij de kast van ${status.naam || "jou"}`
                 + ` op ${stand.basis || "deze server"}.`
                 + ` Laatst gesynchroniseerd: ${klok(stand.laatst)}.` })
        : el("p", { class: "toelichting",
            tekst: "Draai je zelf een kastserver, dan kun je dezelfde kast op je "
                 + "telefoon en je pc gebruiken. Zonder server werkt alles hier "
                 + "gewoon door - je kast staat in deze browser en blijft daar." }),

      gekoppeld
        ? el("div", { class: "veldrij" }, [syncknop, afknop])
        : el("div", {}, [
            el("ol", { class: "stappen" }, [
              stap("Start de server op de machine waar hij hoort: ",
                   el("b", { tekst: "py server/kastserver.py" }), "."),
              stap("Maak daar een uitnodiging: ",
                   el("b", { tekst: 'py server/kastserver.py --nodig "Miro"' }),
                   ". De sleutel verschijnt "
                   + "één keer op het scherm en is daarna niet meer op te vragen."),
              stap("Vul hieronder het adres van je server in en plak de sleutel."),
            ]),
            el("div", { class: "veldrij" }, [adresveld]),
            el("div", { class: "veldrij" }, [sleutelveld, aanmeldknop]),
            el("p", { class: "sleeptekst", style: "text-align:left",
              tekst: "Laat het adres leeg als je deze site al ván je eigen "
                   + "server opent. Dan is er niets in te stellen en gaat er "
                   + "ook niets langs een ander domein." }),
          ]),
    ]),

    el("section", { class: "kaart" }, [
      el("h3", { tekst: "Wat er heen en weer gaat" }),
      el("p", { class: "toelichting",
        tekst: "De platen zelf en wat jij erover invulde: staat, je eigen "
             + "vraagprijs, notities, verkocht of niet. Dat is klein — honderd "
             + "platen zijn ongeveer 170 kB, dus dit lukt ook op een trage "
             + "verbinding." }),
      el("p", { class: "toelichting",
        tekst: "Foto's gaan NIET mee. Die zijn duizend keer zo groot en horen "
             + "in een eigen stap; tot dan blijven ze op het apparaat waar je "
             + "ze gemaakt hebt." }),
      el("p", { class: "toelichting",
        tekst: "Veranderen twee apparaten dezelfde plaat, dan wint de laatste "
             + "wijziging. De versie die verliest wordt op de server bewaard en "
             + "niet weggegooid — er is geen geval waarin een notitie van je "
             + "stilletjes verdwijnt." }),
    ]),

    !gekoppeld && status.fout && stand.basis
      ? el("section", { class: "kaart" }, [
          el("h3", { tekst: "De server antwoordde niet" }),
          el("p", { class: "toelichting", tekst: status.fout }),
          el("p", { class: "toelichting",
            tekst: "Staat hij aan? En klopt het adres — met http:// of https:// "
                 + "ervoor en zonder pad erachter?" }),
        ])
      : null,

    melding,
  ]));
}
