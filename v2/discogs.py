#!/usr/bin/env python3
"""
discogs.py - praten met Discogs, met een SQLite-cache en een snelheidsrem.

Wat er anders is dan in v1
--------------------------
De cache was een JSON-bestand dat bij elke twintig aanroepen volledig opnieuw
weggeschreven werd. Dat bestand groeide naar 38 MB, dus tegen het eind kostte
het cachen meer tijd dan het bespaarde. SQLite schrijft alleen de regel die
verandert.

De snelheidsrem is het harde plafond van dit hele project: met een token mag je
60 aanroepen per minuut doen. Geen enkele hoeveelheid rekenkracht verandert
daar iets aan, dus alles wat langs Discogs moet is per definitie serieel. De
rem zit daarom in een slot: ook als er meerdere draden vragen stellen blijft
het totaal onder het plafond.
"""
import os, json, time, sqlite3, threading
import requests

UA = "VinylLister/3.0"
API = "https://api.discogs.com"


class Discogs:
    def __init__(self, token=None, cache="cache/discogs.db"):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = UA
        self.token = token
        self.gap = 1.1 if token else 2.5
        self.last = 0.0
        self.slot = threading.Lock()
        self.treffers = self.missers = 0

        os.makedirs(os.path.dirname(cache) or ".", exist_ok=True)
        self.db = sqlite3.connect(cache, check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS cache "
                        "(sleutel TEXT PRIMARY KEY, waarde TEXT)")
        self.db.commit()
        self.dblock = threading.Lock()

    # ---------------------------------------------------------------- cache --

    def _lees(self, sleutel):
        with self.dblock:
            r = self.db.execute("SELECT waarde FROM cache WHERE sleutel=?",
                                (sleutel,)).fetchone()
        return json.loads(r[0]) if r else None

    def _schrijf(self, sleutel, waarde):
        with self.dblock:
            self.db.execute("INSERT OR REPLACE INTO cache VALUES (?,?)",
                            (sleutel, json.dumps(waarde, ensure_ascii=False)))
            self.db.commit()

    def uit_json(self, pad):
        """Neemt een oude v1-cache over. Scheelt duizenden aanroepen."""
        if not os.path.exists(pad):
            return 0
        try:
            oud = json.load(open(pad, encoding="utf-8"))
        except Exception:
            return 0
        with self.dblock:
            self.db.executemany(
                "INSERT OR IGNORE INTO cache VALUES (?,?)",
                [(k, json.dumps(v, ensure_ascii=False)) for k, v in oud.items()])
            self.db.commit()
        return len(oud)

    def aantal(self):
        with self.dblock:
            return self.db.execute("SELECT COUNT(*) FROM cache").fetchone()[0]

    # ------------------------------------------------------------- verkeer --

    def get(self, pad, **params):
        sleutel = pad + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items())
                                       if k != "token")
        uit = self._lees(sleutel)
        if uit is not None:
            self.treffers += 1
            return uit
        self.missers += 1
        uit = self._haal(pad, **params)
        self._schrijf(sleutel, uit)
        return uit

    def _haal(self, pad, **params):
        if self.token:
            params["token"] = self.token
        for poging in range(4):
            with self.slot:                     # de rem geldt voor alle draden
                w = self.gap - (time.time() - self.last)
                if w > 0:
                    time.sleep(w)
                self.last = time.time()
            try:
                r = self.s.get(API + pad, params=params, timeout=25)
            except requests.RequestException:
                time.sleep(4 * (poging + 1))
                continue
            if r.status_code == 429:
                time.sleep(8 * (poging + 1))
                continue
            return r.json() if r.ok else None
        return None

    def zoek(self, **kw):
        return (self.get("/database/search", type="release", **kw) or {}).get("results", [])

    def search(self, **kw):
        """Zelfde als zoek(); prijs.py komt uit v1 en gebruikt deze naam."""
        kw.pop("type", None)
        return self.zoek(**kw)

    def release(self, rid):
        # curr_abbr staat er omdat de documentatie zegt dat het werkt. Dat doet
        # het niet: lowest_price komt er in dollars uit, met of zonder deze
        # parameter en ongeacht de muntinstelling van de account. Gebruik
        # markt() voor prijzen; deze endpoint is er voor de gegevens.
        return self.get(f"/releases/{rid}", curr_abbr="EUR")

    def markt(self, rid):
        """Aanbod en laagste prijs, en dan uit de JUISTE endpoint.

        /releases/{id} geeft ook een lowest_price, maar die staat in dollars.
        Gemeten over twaalf platen was hij stelselmatig 1,15x de waarde hier,
        precies de koers USD/EUR; hetzelfde geldt voor /marketplace/fee, die
        "USD" gewoon opschrijft. Deze endpoint zegt zelf in welke munt hij
        rekent, en dat is de enige reden om hem te vertrouwen:

            {"num_for_sale": 1,
             "lowest_price": {"value": 39.0, "currency": "EUR"},
             "blocked_from_sale": false}
        """
        return self.get(f"/marketplace/stats/{rid}")

    def suggestions(self, rid):
        """De echte prijsgids (VG+/NM/VG), en de enige bron die zegt waarvoor
        platen WEGGAAN in plaats van waarvoor ze te koop staan.

        Geeft 404 "You must fill out your seller settings first" zolang de
        verkopersinstellingen op discogs.com niet ingevuld zijn, want de gids
        rekent in de listing-valuta van de verkoper en die weet hij dan niet.
        Zolang dat zo is valt prijs.py terug op markt().
        """
        return self.get(f"/marketplace/price_suggestions/{rid}")

    # v1 riep dit aan om de JSON-cache weg te schrijven; met SQLite is elke
    # regel al bewaard zodra hij binnenkomt.
    def bewaar(self, altijd=False):
        return None
