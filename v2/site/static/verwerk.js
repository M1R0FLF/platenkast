/* verwerk.js - foto's erin, platen eruit. Op je telefoon net zo goed als op je pc.
 *
 * Wat hier vroeger stond
 * ----------------------
 * Een scherm dat om een MAPPAD vroeg. De browser mag geen pad geven, dus daar
 * zat een knop achter die de server een Windows-mapkiezer liet openen - en die
 * server draaide alleen op 127.0.0.1. Op een telefoon werd dit scherm dus een
 * bladzijde met opdrachten die je daar niet kunt uitvoeren.
 *
 * Nu is het een WACHTRIJ, en dat is geen andere vormgeving maar een ander
 * model. Een map met tweehonderd foto's bestaat niet op een telefoon; een
 * plaat in je hand wel. Je maakt twee foto's, die plaat staat in de rij, en de
 * motor werkt hem af terwijl jij de volgende pakt.
 *
 * Waarom er zoveel voortgang op het scherm staat
 * ---------------------------------------------
 * Een plaat kost in de browser tientallen seconden: snijden, lezen, opzoeken,
 * prijzen. Zonder zichtbaar teken van leven is "traag" niet te onderscheiden
 * van "vastgelopen" - dat overkwam mij tijdens het bouwen ook, en ik wist waar
 * ik naar keek. Dus: een balk die zegt hoe ver, de hoes die rechtop verschijnt
 * zodra hij gesneden is, en de seconden erbij. Wie kan zien dat er iets
 * gebeurt, wacht rustig; wie dat niet kan, laadt de pagina opnieuw en gooit
 * het werk weg.
 *
 * De rij staat in IndexedDB, met de foto's erin. Je kunt de app dus wegleggen
 * en morgen verdergaan, en - dat is de andere reden - er zit nergens de aanname
 * in dat de foto's "op een schijf staan". Dat is de vorm die straks naar een
 * account te tillen is.
 */
import { el, euro, getal, toon } from "./ui.js";
import * as opslag from "./opslag.js";
import * as motor from "./motor.js";

/* Op een telefoon opent `capture` meteen de camera in plaats van de fotorol.
 * Op een pc doet het attribuut niets, dus het staat er altijd - maar de knop
 * heet daar anders, want "Foto maken" met een webcam is niet wat je wilt. */
const TELEFOON = matchMedia("(pointer: coarse)").matches;

let draait = false;
let herteken = async () => {};

/* ------------------------------------------------------------ foto's erin -- */

function kies({ meerdere = false, camera = false }) {
  return new Promise(op => {
    const invoer = el("input", { type: "file", accept: "image/*" });
    if (meerdere) invoer.multiple = true;
    if (camera) invoer.capture = "environment";
    invoer.addEventListener("change", () => op([...invoer.files]));
    invoer.click();
  });
}

/** Losse foto's -> platen, twee aan twee.
 *
 *  Voorkant, achterkant, voorkant, achterkant - dat is de volgorde waarin er
 *  gefotografeerd wordt en die is betrouwbaarder dan wat dan ook uit het beeld.
 *  Een oneven laatste foto wordt een plaat met alleen een voorkant; dat mag,
 *  `groep.maak_plaat` kan daarmee om. */
async function voegToe(bestanden) {
  if (!bestanden.length) return 0;
  const op = [...bestanden].sort((a, b) =>
    a.name.localeCompare(b.name, "nl", { numeric: true }));
  let n = 0;
  for (let i = 0; i < op.length; i += 2) {
    await opslag.zetInWachtrij(op.slice(i, i + 2).map(f => ({ naam: f.name, blob: f })));
    n++;
  }
  await herteken();
  return n;
}

/* ------------------------------------------------------------- voortgang -- */

/* Hoeveel procent klaar is bij elke stap. Grof, en dat mag: het gaat er niet om
 * dat de balk klopt op de seconde, het gaat erom dat hij BEWEEGT. Een balk die
 * blijft staan is erger dan geen balk - dan denk je dat het vastzit.
 *
 * De verhouding komt uit de meting: lezen is verreweg het duurst, opzoeken
 * kost een paar seconden, de prijs een enkele aanroep. */
function procent(b, aantalFotos) {
  const perFoto = 70 / Math.max(aantalFotos, 1);
  switch (b.stap) {
    case "foto":      return (b.n - 1) * perFoto;
    case "hoes":      return b.n * perFoto;
    case "zoeken":    return 70;
    case "gevonden":  return 90;
    case "onherkend": return 100;
    case "prijs":     return 95;
    case "klaar":     return 100;
    default:          return 0;
  }
}

function stapTekst(b) {
  switch (b.stap) {
    case "foto":   return `foto ${b.n} van ${b.totaal} uitsnijden en lezen`;
    case "hoes":   return `foto ${b.n} gelezen — ${b.regels} tekstregels`;
    case "zoeken": return b.catno && b.catno.length
      ? `persing zoeken op ${b.catno.join(", ")}`
      : "persing zoeken";
    case "gevonden":  return `${b.artiest || "?"} — ${b.titel || "?"}`;
    case "prijs":     return "marktprijs opzoeken";
    case "klaar":     return "klaar";
    case "onherkend": return b.reden || "niet herkend";
    default:          return "";
  }
}

/** Het paneel dat laat zien wat er NU gebeurt. */
function maakBezigPaneel() {
  const beeld = el("div", { class: "bezigbeeld" });
  const balk = el("i");
  const titel = el("div", { class: "bezigtitel", tekst: "Bezig..." });
  const stap = el("div", { class: "bezigstap" });
  const klok = el("span", { class: "bezigklok" });

  const paneel = el("section", { class: "kaart bezig", style: "display:none" }, [
    beeld,
    el("div", { style: "flex:1;min-width:0" }, [
      titel, stap,
      el("div", { class: "voortgang", style: "margin:10px 0 6px" }, [balk]),
      klok,
    ]),
  ]);

  let t0 = 0, tikker = null, aantalFotos = 2;

  return {
    knoop: paneel,
    begin(rij) {
      aantalFotos = rij.fotos.length || 2;
      t0 = Date.now();
      paneel.style.display = "";
      balk.style.width = "2%";
      titel.textContent = `${aantalFotos} foto's`;
      stap.textContent = "de motor pakt hem op";
      beeld.replaceChildren();
      // De foto zoals jij hem maakte, tot de uitsnede er is.
      if (rij.fotos[0] && rij.fotos[0].blob) toonBeeld(beeld, rij.fotos[0].blob);
      clearInterval(tikker);
      tikker = setInterval(() => {
        klok.textContent = `${Math.round((Date.now() - t0) / 1000)}s`;
      }, 500);
    },
    melding(b) {
      balk.style.width = `${Math.max(2, procent(b, aantalFotos))}%`;
      stap.textContent = stapTekst(b);
      if (b.stap === "gevonden" || b.stap === "klaar") {
        titel.textContent = `${b.artiest || "?"} — ${b.titel || "?"}`;
      }
      // De verse uitsnede, rechtop. Dit is het moment waarop je ziet dat het
      // werkt, nog voor er een naam bij staat.
      if (b.stap === "hoes" && b.blob) toonBeeld(beeld, b.blob);
    },
    eind() {
      clearInterval(tikker);
      paneel.style.display = "none";
    },
  };
}

function toonBeeld(houder, blob) {
  const u = URL.createObjectURL(blob);
  const img = el("img", { src: u, alt: "" });
  img.addEventListener("load", () => URL.revokeObjectURL(u));
  houder.replaceChildren(img);
}

/* ------------------------------------------------------------ het scorebord -- */

function scorebord(rijen) {
  const klaar = rijen.filter(r => r.staat === "klaar");
  const waarde = klaar.reduce((t, r) => t + ((r.plaat && r.plaat.prijs) || 0), 0);
  const seconden = rijen.reduce(
    (t, r) => t + (r.tijden ? Object.values(r.tijden).reduce((a, b) => a + b, 0) : 0), 0);
  const gedaan = rijen.filter(r => r.staat === "klaar" || r.staat === "onherkend").length;

  const cijfer = (waarde_, label, titel) =>
    el("div", { class: "kerncijfer", title: titel || "" },
       [el("b", { tekst: waarde_ }), el("span", { tekst: label })]);

  return el("div", { class: "kerncijfers" }, [
    cijfer(getal(klaar.length), "in de kast"),
    cijfer(euro(waarde), "samen waard"),
    cijfer(gedaan ? `${Math.round(seconden / gedaan)}s` : "-", "per plaat",
           "gemiddelde verwerkingstijd op dit apparaat"),
  ]);
}

/* ------------------------------------------------------------- de afwerklus -- */

async function werkAf(zetStand, bezig) {
  if (draait) return;
  draait = true;
  await herteken();
  try {
    if (!motor.isKlaar()) {
      zetStand("De motor start op. De eerste keer haalt hij ongeveer 40 MB op; "
             + "daarna staat hij in je browser en gaat het meteen.");
      await motor.start(m => {
        if (m.soort === "stap") zetStand(`Motor starten — ${m.tekst}...`);
      });
    }
    zetStand("");

    for (;;) {
      const wacht = (await opslag.wachtrij()).filter(r => r.staat === "wacht");
      if (!wacht.length) break;
      const rij = wacht[0];

      await opslag.wijzig(rij.id, { staat: "bezig" });
      bezig.begin(rij);
      await herteken();

      try {
        const uit = await motor.verwerk(rij.fotos, {
          token: token(), opVoortgang: b => bezig.melding(b),
        });
        await bewaarUitslag(rij, uit);
      } catch (e) {
        await opslag.wijzig(rij.id, { staat: "mislukt", reden: e.message });
      }
      bezig.eind();
      await herteken();
    }
  } catch (e) {
    zetStand(`De motor kwam niet op gang: ${e.message}`);
    await opslag.hervat();
  } finally {
    bezig.eind();
    draait = false;
    await herteken();
  }
}

async function bewaarUitslag(rij, uit) {
  const k = uit.kern || {};
  const hoezen = uit.hoezen || [];

  // Een gevonden persing die alleen geen PRIJS kreeg is geen mislukking. Dat
  // onderscheid stond er eerst niet in, en dan verdwijnt een correct herkende
  // plaat in de bak "zelf opzoeken" omdat de marktprijs niet opgehaald kon
  // worden - precies andersom als wat je wilt.
  if (k.ok && !k.kastplaat) {
    await opslag.wijzig(rij.id, {
      staat: "mislukt",
      reden: "persing gevonden, maar de prijs mislukte: "
           + (k.prijsfout || "onbekende fout").trim().split("\n").pop(),
      koptekst: (k.rec && k.rec.koptekst) || [],
      tijden: k.tijden, hoezen, ruwe: k.plaat || null,
    });
    return;
  }

  if (!k.ok || !k.kastplaat) {
    // Niet herkend is geen fout maar precies wat "liever niets dan iets
    // verkeerds" betekent. De plaat blijft staan met de reden erbij en met de
    // grootst gedrukte regels van de voorkant, want dááraan herken jij hem als
    // je hem zelf gaat opzoeken.
    await opslag.wijzig(rij.id, {
      staat: "onherkend",
      reden: k.reden || "niet herkend",
      koptekst: (k.rec && k.rec.koptekst) || [],
      catno: (k.rec && k.rec.catno_kandidaten) || [],
      tijden: k.tijden, hoezen,
    });
    return;
  }

  const plaat = k.kastplaat;
  await opslag.vulAan({ platen: [plaat] });
  await opslag.wijzig(rij.id, {
    staat: "klaar", plaat, hoezen, reden: null, tijden: k.tijden,
  });
}

/* Het token staat in localStorage en niet in de code: het is van jou, het geeft
 * toegang tot jouw Discogs-account, en het hoort niet in een repository of in
 * een gepubliceerde site te staan. Zonder token werkt alles behalve prijzen,
 * en gaat het van 60 naar 25 aanroepen per minuut. */
const token = () => {
  try { return localStorage.getItem("discogs_token") || null; } catch { return null; }
};

/* Zonder token werkt alles behalve de PRIJS, en gaat Discogs van 60 naar 25
 * aanroepen per minuut. Dat hoort op het scherm te staan en niet als raadsel:
 * een plaat die netjes herkend wordt maar geen bedrag krijgt, is anders een
 * fout die je gaat zoeken. */
function tokenregel() {
  const zetten = async () => {
    const t = prompt("Plak je Discogs-token.\n\nGratis via discogs.com > "
                   + "Settings > Developers > Generate token. Hij blijft in "
                   + "deze browser en gaat nergens anders heen.", token() || "");
    if (t === null) return;
    try { localStorage.setItem("discogs_token", t.trim()); } catch {}
    await herteken();
  };
  return token()
    ? el("p", { class: "sleeptekst", style: "text-align:left" }, [
        "Discogs-token staat klaar. ",
        el("a", { href: "#", onclick: e => { e.preventDefault(); zetten(); },
                  tekst: "wijzigen" }),
      ])
    : el("p", { class: "sleeptekst", style: "text-align:left;color:var(--twijfel)" }, [
        "Zonder Discogs-token krijg je geen prijzen, en gaat het opzoeken van "
        + "60 naar 25 aanroepen per minuut. ",
        el("a", { href: "#", onclick: e => { e.preventDefault(); zetten(); },
                  tekst: "token instellen" }),
      ]);
}

/* ------------------------------------------------------------------ scherm -- */

const STAAT = {
  wacht: { tekst: "wacht", klasse: "" },
  bezig: { tekst: "bezig", klasse: "twijfel" },
  klaar: { tekst: "in de kast", klasse: "goed" },
  onherkend: { tekst: "zelf opzoeken", klasse: "twijfel" },
  mislukt: { tekst: "mislukt", klasse: "fout" },
};

function tegel(rij) {
  const duim = el("div", { class: "rijduim" });
  const bron = (rij.hoezen && rij.hoezen[0] && rij.hoezen[0].blob)
            || (rij.fotos && rij.fotos[0] && rij.fotos[0].blob);
  if (bron) toonBeeld(duim, bron);

  const s = STAAT[rij.staat] || STAAT.wacht;
  const kop = rij.plaat
    ? `${rij.plaat.artiest || "?"} — ${rij.plaat.titel || "?"}`
    : (rij.koptekst && rij.koptekst[0])
      || `${rij.fotos.length} foto${rij.fotos.length === 1 ? "" : "'s"}`;

  const onder = [];
  if (rij.plaat) {
    const p = rij.plaat;
    onder.push([p.label, p.catno, p.land, p.jaar].filter(Boolean).join(" · "));
  } else if (rij.reden) {
    onder.push(rij.reden);
  }
  if (rij.tijden) {
    onder.push(`${Object.values(rij.tijden).reduce((a, b) => a + b, 0).toFixed(0)}s`);
  }

  return el("div", { class: "rijkaart" }, [
    duim,
    el("div", { style: "flex:1;min-width:0" }, [
      el("div", { class: "rijkop", tekst: kop }),
      el("div", { class: "rijonder", tekst: onder.filter(Boolean).join("  ·  ") }),
    ]),
    rij.plaat && rij.plaat.prijs
      ? el("b", { class: "rijprijs", tekst: euro(rij.plaat.prijs) }) : null,
    el("span", { class: `stempel ${s.klasse}`, tekst: s.tekst }),
    el("button", {
      class: "knop klein", tekst: "×", title: "uit de rij halen",
      onclick: async () => { await opslag.uitWachtrij(rij.id); await herteken(); },
    }),
  ]);
}

export async function scherm(data, herlaad) {
  // Een plaat kan alleen "bezig" zijn zolang er een motor loopt. Is de pagina
  // opnieuw geladen, dan is dat niet zo - dus dit is geen herstel maar het
  // rechtzetten van een onwaarheid.
  await opslag.hervat();

  const stand = el("p", { class: "stand" });
  const lijst = el("div", { class: "rijlijst" });
  const cijfers = el("div");
  const bezig = maakBezigPaneel();
  const zetStand = t => { stand.textContent = t; stand.style.display = t ? "" : "none"; };

  const knop = el("button", { class: "knop fel",
                              onclick: () => werkAf(zetStand, bezig) });

  herteken = async () => {
    const rijen = await opslag.wachtrij();
    lijst.replaceChildren(...(rijen.length
      ? rijen.map(tegel)
      : [el("p", { class: "leegrij", tekst: "Nog niets in de rij." })]));
    cijfers.replaceChildren(rijen.some(r => r.staat === "klaar")
      ? scorebord(rijen) : el("span"));
    const wacht = rijen.filter(r => r.staat === "wacht").length;
    knop.disabled = !wacht || draait;
    knop.textContent = draait ? "Bezig..."
      : wacht ? `${wacht} plaat${wacht === 1 ? "" : "en"} verwerken`
              : "Niets te doen";
    if (rijen.some(r => r.staat === "klaar")) herlaad(false);
  };

  const camera = el("button", {
    class: "knop fel", tekst: TELEFOON ? "Foto maken" : "Foto's kiezen",
    onclick: async () => voegToe(await kies({ camera: TELEFOON, meerdere: !TELEFOON })),
  });
  const rol = TELEFOON ? el("button", {
    class: "knop", tekst: "Uit je fotorol",
    onclick: async () => voegToe(await kies({ meerdere: true })),
  }) : null;

  const zone = el("div", { class: "sleepzone" }, [
    el("div", { class: "veldrij" }, [camera, rol].filter(Boolean)),
    el("p", { class: "sleeptekst",
      tekst: TELEFOON
        ? "Voorkant, dan achterkant. Elke twee foto's zijn één plaat."
        : "Of sleep je foto's hierheen. Voorkant, dan achterkant: "
        + "elke twee foto's zijn één plaat." }),
  ]);
  zone.addEventListener("dragover", e => { e.preventDefault(); zone.classList.add("over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("over"));
  zone.addEventListener("drop", async e => {
    e.preventDefault();
    zone.classList.remove("over");
    const b = [...e.dataTransfer.files].filter(f => f.type.startsWith("image/"));
    if (b.length) await voegToe(b);
  });

  toon(el("div", {}, [
    el("section", { class: "kaart" }, [
      el("h3", { tekst: "Foto's verwerken" }),
      el("p", { class: "toelichting",
        tekst: "Het herkennen gebeurt in deze browser: je foto's gaan nergens "
             + "heen. Alleen om de persing en de prijs op te zoeken wordt "
             + "Discogs geraadpleegd." }),
      zone,
      tokenregel(),
    ]),
    bezig.knoop,
    el("section", { class: "kaart" }, [
      el("div", { class: "veldrij", style: "align-items:center" }, [
        el("h3", { style: "flex:1;margin:0", tekst: "In de rij" }), knop,
      ]),
      stand,
      cijfers,
      lijst,
    ]),
  ]));

  zetStand("");
  await herteken();
}
