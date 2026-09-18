/* invoer.js - je Discogs-collectie ophalen.
 *
 * Wie al jaren op Discogs bijhoudt wat hij heeft, wil zijn kast niet opnieuw
 * fotograferen. Die platen zijn daar al door een mens geidentificeerd, met een
 * release-id erbij - dat is nauwkeuriger dan wat de camera ooit gaat halen.
 *
 * Hier komt dus GEEN Pyodide aan te pas. Dit is een lijst ophalen en omzetten;
 * het zware werk is alleen nodig voor platen die nergens vastliggen.
 *
 * Waarom de platen "overgenomen" heten en niet "zeker"
 * ---------------------------------------------------
 * "Zeker" betekent in deze kast iets heel bepaalds: het catalogusnummer van
 * deze persing staat op de hoes, gelezen door de machine. Dat is hier niet
 * gebeurd. Wat hier staat is door JOU gekozen op Discogs, en dat is meestal
 * beter - maar het is een ander soort zekerheid, en die twee door elkaar halen
 * maakt het stempel betekenisloos. Vandaar een eigen niveau.
 *
 * Wat er NIET meekomt
 * -------------------
 * De collectielijst geeft alleen `basic_information`: artiest, titel, label,
 * catalogusnummer, jaar, formaat en een duimnagel. Geen land, geen tracklist,
 * geen prijs. Die zitten in /releases/{id}, en dat is een aanroep per plaat
 * tegen een plafond van 60 per minuut - vijfhonderd platen is dan acht minuten.
 * Daarom is dat een aparte, optionele ronde en niet iets dat stilletjes gebeurt.
 */

const API = "https://api.discogs.com";

/* Discogs noemt een 7" een "Vinyl" met beschrijvingen erbij. De kast kent vier
 * soorten; de rest wordt LP, want dat is wat een plaat meestal is. */
function soortVan(formats) {
  const d = (formats || []).flatMap(f => (f.descriptions || []).concat(f.name || []))
                           .join(" ").toLowerCase();
  if (d.includes('7"')) return "single7";
  if (d.includes('12"') && d.includes("maxi")) return "maxi12";
  if (d.includes("ep")) return "EP";
  return "LP";
}

function formaatVan(formats) {
  return (formats || []).map(f => [
    f.qty && +f.qty > 1 ? `${f.qty}x` : null, f.name,
    ...(f.descriptions || []),
  ].filter(Boolean).join(" ")).join(", ");
}

/** Een regel uit de collectie -> een plaat zoals de kast hem kent. */
export function naarPlaat(item) {
  const b = item.basic_information || {};
  const labels = b.labels || [];
  // De artiestnaam op Discogs kan "Gaynor, Gloria (2)" zijn: het cijfer
  // onderscheidt naamgenoten en hoort niet op je scherm.
  const artiest = (b.artists || []).map(a => (a.name || "").replace(/\s*\(\d+\)$/, ""))
                                   .join(" / ") || null;
  return {
    id: `dc${b.id}`,                    // eigen ruimte, botst niet met foto-id's
    artiest,
    titel: b.title || null,
    soort: soortVan(b.formats),
    jaar: b.year || null,
    label: labels.map(l => l.name).filter(Boolean).join(", ") || null,
    catno: (labels[0] || {}).catno || null,
    land: null,                          // zit niet in basic_information
    genres: (b.genres || []).concat(b.styles || []),
    formaat: formaatVan(b.formats),
    tracks: [],
    prijs: null,
    markt: {},
    discogs: `https://www.discogs.com/release/${b.id}`,
    release_id: b.id,
    oordeel: "overgenomen",
    oordeel_reden: ["staat in jouw Discogs-collectie, door jou gekozen"],
    beeld_punten: null,
    herkend_op: "discogs-collectie",
    duim: b.cover_image || b.thumb || null,
    fotos: [],
  };
}

async function vraag(pad, token, params = {}) {
  const u = new URL(API + pad);
  Object.entries(params).forEach(([k, v]) => u.searchParams.set(k, v));
  const r = await fetch(u, {
    headers: token ? { authorization: `Discogs token=${token}` } : {},
  });
  if (r.status === 401 || r.status === 403) {
    throw new Error("Discogs weigert dit token. Klopt hij, en is hij van het "
                  + "type 'personal access token'?");
  }
  if (r.status === 429) {
    throw new Error("Discogs houdt je even tegen (te veel aanroepen). "
                  + "Probeer het over een minuut opnieuw.");
  }
  if (!r.ok) throw new Error(`Discogs antwoordde ${r.status}`);
  return r.json();
}

export async function wieBenJe(token) {
  const d = await vraag("/oauth/identity", token);
  return d.username;
}

/** De hele collectie ophalen, bladzijde voor bladzijde.
 *
 *  `opVoortgang({klaar, totaal})` wordt na elke bladzijde aangeroepen: bij een
 *  collectie van vijfhonderd zijn dat tien aanroepen, en dan wil je zien dat er
 *  iets gebeurt. */
export async function haalCollectie(token, opVoortgang = () => {}) {
  const naam = await wieBenJe(token);
  const uit = [];
  let pagina = 1, paginas = 1, totaal = 0;

  do {
    const d = await vraag(`/users/${encodeURIComponent(naam)}/collection/folders/0/releases`,
                          token, { per_page: 100, page: pagina, sort: "artist" });
    const pg = d.pagination || {};
    paginas = pg.pages || 1;
    totaal = pg.items || 0;
    for (const item of (d.releases || [])) uit.push(naarPlaat(item));
    opVoortgang({ klaar: uit.length, totaal, naam });
    pagina++;
  } while (pagina <= paginas);

  return { naam, platen: uit, totaal };
}

/** Tweede, optionele ronde: land, tracklist en marktprijs per plaat.
 *
 *  Een aanroep per plaat, en Discogs laat er zestig per minuut door. Daarom
 *  apart, met een teller, en afbreekbaar - niemand hoort acht minuten naar een
 *  bevroren scherm te kijken zonder dat hij ervoor gekozen heeft.
 */
export async function vulAan(platen, token, opVoortgang = () => {}, stop = () => false) {
  let n = 0;
  for (const p of platen) {
    if (stop()) break;
    try {
      const rel = await vraag(`/releases/${p.release_id}`, token, { curr_abbr: "EUR" });
      p.land = rel.country || null;
      p.tracks = (rel.tracklist || []).map(t => ({ positie: t.position, titel: t.title }));
      if (!p.jaar && rel.year) p.jaar = rel.year;

      const m = await vraag(`/marketplace/stats/${p.release_id}`, token);
      // De munt staat erbij, en die controleren we: zonder token antwoordt
      // Discogs in dollars, en een dollarprijs als euro's wegschrijven scheelt
      // vijftien procent zonder dat iemand het ziet.
      const lp = m.lowest_price;
      if (lp && lp.currency === "EUR" && typeof lp.value === "number") {
        p.markt = { laagste: lp.value, te_koop: m.num_for_sale };
        p.prijs = Math.round(lp.value * 1.1 * 2) / 2 || null;
      } else if (lp) {
        p.markt = { laagste: null, te_koop: m.num_for_sale,
                    opmerking: `Discogs gaf ${lp.currency}, niet EUR` };
      }
    } catch (e) {
      p.markt = { fout: e.message };
    }
    n++;
    opVoortgang({ klaar: n, totaal: platen.length, plaat: p });
  }
  return platen;
}
