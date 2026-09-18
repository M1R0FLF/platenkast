/* isolatie.js - de pagina cross-origin isoleren zonder de server.
 *
 * Waarom dit bestaat
 * ------------------
 * De keten draait op `SharedArrayBuffer`, en die bestaat alleen op een pagina
 * die cross-origin geisoleerd is. Dat vraagt twee koppen van de SERVER:
 *
 *     cross-origin-opener-policy: same-origin
 *     cross-origin-embedder-policy: require-corp
 *
 * `kast.py` stuurt ze, en `site/vercel.json` zou ze moeten sturen. Maar dat is
 * een instelling buiten de code, en als hij om welke reden dan ook niet
 * aankomt, valt de hele motor stil met een melding die de gebruiker niets kan
 * schelen - hij wilde een plaat verwerken.
 *
 * Een service worker kan dezelfde koppen aan de antwoorden hangen VOORDAT de
 * pagina ze ziet. Daarmee hangt het niet meer af van hoe een host is ingesteld.
 * Dat is geen omweg om de server heen: dezelfde beperkingen gelden, alles van
 * buiten moet nog steeds CORP of CORS meesturen. Het verplaatst alleen wie de
 * koppen zet.
 *
 * De eerste keer is er een herlaadbeurt nodig: een service worker beheert de
 * pagina die hem registreerde nog niet. Dat gebeurt hieronder automatisch, een
 * keer, en daarna nooit meer.
 */

if (typeof window === "undefined") {
  /* ---- dit draait IN de service worker ---- */

  self.addEventListener("install", () => self.skipWaiting());
  self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));

  self.addEventListener("fetch", event => {
    const vraag = event.request;
    // Een verzoek dat de browser al zelf afhandelt (range-verzoeken van een
    // videospeler bijvoorbeeld) laten we met rust.
    if (vraag.cache === "only-if-cached" && vraag.mode !== "same-origin") return;

    event.respondWith(
      fetch(vraag)
        .then(antwoord => {
          if (antwoord.status === 0) return antwoord;   // opaque, niets aan te doen
          const koppen = new Headers(antwoord.headers);
          koppen.set("cross-origin-embedder-policy", "require-corp");
          koppen.set("cross-origin-opener-policy", "same-origin");
          return new Response(antwoord.body, {
            status: antwoord.status,
            statusText: antwoord.statusText,
            headers: koppen,
          });
        })
        .catch(e => new Response(String(e && e.message), { status: 502 }))
    );
  });

} else {
  /* ---- dit draait op de PAGINA ---- */

  // Al geisoleerd? Dan doet de server zijn werk en hoeft dit niet.
  if (!window.crossOriginIsolated && "serviceWorker" in navigator) {
    // Eén herlaadbeurt, en niet meer: zonder deze vlag zou een browser die de
    // worker om een andere reden niet activeert in een lus terechtkomen, en
    // dat is erger dan geen isolatie.
    const AL_GEPROBEERD = "isolatie-herladen";
    navigator.serviceWorker.register(document.currentScript.src, { scope: "./" })
      .then(reg => {
        if (reg.active && !navigator.serviceWorker.controller) {
          if (!sessionStorage.getItem(AL_GEPROBEERD)) {
            sessionStorage.setItem(AL_GEPROBEERD, "1");
            window.location.reload();
          }
        }
        reg.addEventListener("updatefound", () => {
          const nieuw = reg.installing;
          if (!nieuw) return;
          nieuw.addEventListener("statechange", () => {
            if (nieuw.state === "activated" && !sessionStorage.getItem(AL_GEPROBEERD)) {
              sessionStorage.setItem(AL_GEPROBEERD, "1");
              window.location.reload();
            }
          });
        });
      })
      .catch(() => {
        // Geen service worker (privemodus, of een browser die het weigert).
        // Dan blijft de melding in verwerk.js staan, en die legt uit wat er
        // moet gebeuren. Hier stilletjes doorgaan is beter dan een tweede
        // foutmelding over hetzelfde.
      });
  }
}
