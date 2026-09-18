#!/usr/bin/env python3
"""
kastserver.py - de kast synchroniseren tussen je apparaten.

    py server/kastserver.py --nodig "Miro"     een uitnodiging maken
    py server/kastserver.py                    de server draaien
    py server/kastserver.py --wie              wie er accounts hebben

Waarom dit een APART programma is en niet kast.py erbij
-------------------------------------------------------
`kast.py` draait op jouw machine, als jou, met toegang tot jouw schijf. Hij
heeft geen authenticatie, `/api/kies-map` opent een echt venster op je
bureaublad en `/api/publiceer` doet een `git push`. Dat is prima voor
127.0.0.1 en onverdedigbaar op het open internet. Het zijn twee verschillende
programma's omdat het twee verschillende vertrouwensniveaus zijn.

Deze server rekent NIETS uit. De keten draait in de browser van de gebruiker;
hier komt alleen JSON binnen en gaat JSON uit. Dat is de reden dat een oude
desktop hier genoeg aan heeft: honderd platen zijn 172 KB.

Uitnodigingen nu, accounts later
--------------------------------
Er is met opzet geen wachtwoord. Een uitnodiging is een lange willekeurige
sleutel; wie hem heeft mag bij die kast. Dat scheelt wachtwoorden hashen,
sessies opnieuw uitvinden en een vergeten-wachtwoordstroom bouwen.

Maar het kan hier niet blijven, want er kan geld achter komen te zitten. Dus:

    NIETS hangt aan de uitnodiging. Alles hangt aan `gebruiker.id`.

De uitnodiging is een RIJ in `login`, naast de rijen die er later bij komen
(e-mail met wachtwoord, misschien Discogs). Een echte account aanzetten is dan
een regel toevoegen aan `login` - niet een migratie van andermans platen.

Wat er NIET in zit
------------------
Foto's. Die zijn de volgende stap en een andere orde van grootte: ~5 MB per
originele foto tegenover ~1,7 KB per plaat aan gegevens. Het schema staat ze
niet in de weg, maar ze door deze tabellen persen zou betekenen dat een sync
van je aantekeningen wacht op een upload van een gigabyte.
"""
import os, re, sys, json, time, uuid, secrets, sqlite3, hashlib, argparse
import http.cookies, urllib.parse
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

HIER = os.path.dirname(os.path.abspath(__file__))
WORTEL = os.path.dirname(HIER)
sys.path.insert(0, WORTEL)

POORT = 7386
DB = os.path.join(HIER, "kast.db")
KOEKJE = "kast_sessie"
SESSIE_DAGEN = 400

# Dezelfde twee koppen als kast.py en vercel.json. Zonder deze draait de motor
# niet: Pyodide roept de OCR synchroon aan, onnxruntime-web antwoordt
# asynchroon, en die twee vinden elkaar over een SharedArrayBuffer. Die bestaat
# alleen op een cross-origin geisoleerde pagina.
#
# Dit is ook meteen de valkuil van een tunnel of een omgekeerde proxy ervoor:
# knipt die de koppen weg, dan laadt de site gewoon en doet alleen het
# verwerken het niet. Zie LEESMIJ.md.
ISOLATIE = [
    ("cross-origin-opener-policy", "same-origin"),
    ("cross-origin-embedder-policy", "require-corp"),
]

SCHEMA = """
PRAGMA journal_mode = WAL;

-- De gebruiker. Zijn id is willekeurig en betekent niets: niet de
-- uitnodigingssleutel, niet een e-mailadres, niet een volgnummer. Alles
-- hieronder wijst hiernaar, zodat er later een andere manier van inloggen bij
-- kan zonder dat er een rij verhuist.
CREATE TABLE IF NOT EXISTS gebruiker (
  id       TEXT PRIMARY KEY,
  naam     TEXT,
  gemaakt  TEXT NOT NULL
);

-- EEN manier om op een gebruiker in te loggen. Nu alleen 'uitnodiging'.
-- Straks komt hier 'wachtwoord' bij (kenmerk = e-mailadres, geheim = een
-- ECHTE afleiding, geen sha256 - zie _hash hieronder) en dan heeft dezelfde
-- gebruiker twee rijen en verandert er verder niets.
CREATE TABLE IF NOT EXISTS login (
  id          INTEGER PRIMARY KEY,
  gebruiker   TEXT NOT NULL REFERENCES gebruiker(id) ON DELETE CASCADE,
  soort       TEXT NOT NULL,
  kenmerk     TEXT,
  geheim      TEXT NOT NULL UNIQUE,
  gemaakt     TEXT NOT NULL,
  gebruikt    TEXT,
  ingetrokken TEXT
);

CREATE TABLE IF NOT EXISTS sessie (
  geheim     TEXT PRIMARY KEY,
  gebruiker  TEXT NOT NULL REFERENCES gebruiker(id) ON DELETE CASCADE,
  gemaakt    TEXT NOT NULL,
  gezien     TEXT NOT NULL
);

-- De uitgerekende laag. Wegwerpbaar: draait de keten opnieuw, dan komt hier
-- iets nieuws te staan. Daarom mag hier de laatste schrijver winnen.
CREATE TABLE IF NOT EXISTS plaat (
  gebruiker  TEXT NOT NULL,
  id         TEXT NOT NULL,
  gewijzigd  TEXT NOT NULL,
  weg        INTEGER NOT NULL DEFAULT 0,
  doc        TEXT,
  PRIMARY KEY (gebruiker, id)
);

-- Wat de gebruiker ZELF invulde: staat, eigen vraagprijs, notitie, verkocht.
-- Dit is het enige in de hele kast dat niet opnieuw uit te rekenen is.
CREATE TABLE IF NOT EXISTS eigen (
  gebruiker  TEXT NOT NULL,
  id         TEXT NOT NULL,
  gewijzigd  TEXT NOT NULL,
  weg        INTEGER NOT NULL DEFAULT 0,
  doc        TEXT,
  PRIMARY KEY (gebruiker, id)
);

-- Elke overschreven versie van een `eigen`-record, voor altijd.
--
-- Twee apparaten die allebei iets invullen betekent dat er een verliest, en
-- "de nieuwste wint" is een regel die af en toe het verkeerde antwoord geeft -
-- bijvoorbeeld als een telefoon een scheve klok heeft. Dit is geen grote
-- tabel: een notitie is een paar honderd bytes en dit gebeurt zelden. Het
-- alternatief is dat iemands aantekening stilletjes weg is, en dat is precies
-- wat deze kast nergens anders doet.
CREATE TABLE IF NOT EXISTS eigen_historie (
  id         INTEGER PRIMARY KEY,
  gebruiker  TEXT NOT NULL,
  plaat      TEXT NOT NULL,
  gewijzigd  TEXT NOT NULL,
  vervangen  TEXT NOT NULL,
  doc        TEXT
);

CREATE TABLE IF NOT EXISTS kast (
  gebruiker  TEXT PRIMARY KEY,
  naam       TEXT,
  gewijzigd  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS plaat_sinds ON plaat (gebruiker, gewijzigd);
CREATE INDEX IF NOT EXISTS eigen_sinds ON eigen (gebruiker, gewijzigd);
"""


def nu(t=None):
    """Een tijdstempel met MILLISECONDEN, en dat is geen sierlijkheid.

    Alle vergelijkingen hieronder zijn tekstvergelijkingen - dat mag, want ISO
    8601 in UTC sorteert gelijk aan de tijd zelf. Maar dan moeten alle stempels
    WEL dezelfde vorm hebben. Zet de browser er ".123Z" achter (zo schrijft
    `toISOString()` het) en de server hier "Z", dan sorteert het punt VOOR de
    Z en is een record uit de browser altijd ouder dan een van de server,
    binnen dezelfde seconde. Dat is precies het soort verschil dat pas opvalt
    als er een notitie kwijt is.

    Meteen de reden dat seconden niet genoeg zijn: twee keer iets intikken
    binnen een seconde is normaal, en dan zou de tweede wijziging geweigerd
    worden omdat hij niet NIEUWER is dan de eerste.
    """
    t = time.time() if t is None else t
    return (time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t))
            + f".{int(t * 1000) % 1000:03d}Z")


def _hash(geheim):
    """Een sleutel wordt nooit zelf bewaard, alleen zijn afdruk.

    sha256 en niet bcrypt/argon2, en dat is hier geen luiheid: die zijn traag
    gemaakt omdat een MENS zijn wachtwoord verzint en dat te raden valt. Een
    uitnodiging hieronder is 256 bits uit `secrets`, en dat raadt niemand -
    langzaam hashen beschermt dan tegen niets en kost alleen tijd.

    Komen er wachtwoorden, dan MOET dat anders. Vandaar dat `login.soort`
    bestaat: dan kiest de controle per soort zijn eigen afleiding.
    """
    return hashlib.sha256(geheim.encode("utf-8")).hexdigest()


def verbind(pad=DB):
    db = sqlite3.connect(pad, check_same_thread=False, timeout=20)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(SCHEMA)
    return db


# ------------------------------------------------------------------ accounts --

def maak_uitnodiging(db, naam, gebruiker=None):
    """Een nieuwe kast met een sleutel, of een tweede sleutel voor een bestaande.

    Geeft de sleutel EEN keer terug; hierna staat alleen zijn afdruk in de
    database en is hij niet meer op te vragen. Dat is expres: een sleutel die
    de server kan teruglezen is een sleutel die uit de server kan lekken.
    """
    if gebruiker is None:
        gebruiker = uuid.uuid4().hex
        db.execute("INSERT INTO gebruiker (id, naam, gemaakt) VALUES (?,?,?)",
                   (gebruiker, naam, nu()))
    elif not db.execute("SELECT 1 FROM gebruiker WHERE id=?", (gebruiker,)).fetchone():
        raise ValueError(f"onbekende gebruiker: {gebruiker}")
    sleutel = secrets.token_urlsafe(32)
    db.execute("INSERT INTO login (gebruiker, soort, kenmerk, geheim, gemaakt) "
               "VALUES (?,'uitnodiging',NULL,?,?)",
               (gebruiker, _hash(sleutel), nu()))
    db.commit()
    return gebruiker, sleutel


def meld_aan(db, sleutel):
    """Sleutel inwisselen voor een sessie. Geeft (gebruiker_id, sessiegeheim)."""
    r = db.execute("SELECT * FROM login WHERE geheim=? AND ingetrokken IS NULL",
                   (_hash((sleutel or "").strip()),)).fetchone()
    if not r:
        return None, None
    geheim = secrets.token_urlsafe(32)
    db.execute("INSERT INTO sessie (geheim, gebruiker, gemaakt, gezien) VALUES (?,?,?,?)",
               (_hash(geheim), r["gebruiker"], nu(), nu()))
    db.execute("UPDATE login SET gebruikt=? WHERE id=?", (nu(), r["id"]))
    db.commit()
    return r["gebruiker"], geheim


def wie(db, geheim):
    if not geheim:
        return None
    r = db.execute(
        "SELECT s.gebruiker, g.naam FROM sessie s JOIN gebruiker g ON g.id=s.gebruiker "
        "WHERE s.geheim=? AND s.gemaakt > ?",
        (_hash(geheim), nu(time.time() - SESSIE_DAGEN * 86400))
    ).fetchone()
    if r:
        db.execute("UPDATE sessie SET gezien=? WHERE geheim=?", (nu(), _hash(geheim)))
        db.commit()
    return r


def meld_af(db, geheim):
    if geheim:
        db.execute("DELETE FROM sessie WHERE geheim=?", (_hash(geheim),))
        db.commit()


# ---------------------------------------------------------------------- sync --

MAX_RECORDS = 20000          # een kast van 20.000 platen bestaat niet
MAX_LICHAAM = 64 * 1024 * 1024


def haal(db, gebruiker, sinds=""):
    """Alles wat sinds `sinds` veranderde. Zonder `sinds`: de hele kast."""
    sinds = sinds or ""
    platen = db.execute(
        "SELECT id, gewijzigd, weg, doc FROM plaat WHERE gebruiker=? AND gewijzigd > ? "
        "ORDER BY gewijzigd", (gebruiker, sinds)).fetchall()
    eigen = db.execute(
        "SELECT id, gewijzigd, weg, doc FROM eigen WHERE gebruiker=? AND gewijzigd > ? "
        "ORDER BY gewijzigd", (gebruiker, sinds)).fetchall()
    k = db.execute("SELECT naam, gewijzigd FROM kast WHERE gebruiker=?",
                   (gebruiker,)).fetchone()

    def uit(rij):
        d = {"id": rij["id"], "gewijzigd": rij["gewijzigd"]}
        if rij["weg"]:
            d["weg"] = True
        else:
            d["doc"] = json.loads(rij["doc"]) if rij["doc"] else {}
        return d

    return {
        "nu": nu(),
        "sinds": sinds,
        "platen": [uit(r) for r in platen],
        "eigen": [uit(r) for r in eigen],
        "naam": k["naam"] if k else None,
        "naam_gewijzigd": k["gewijzigd"] if k else None,
    }


def _zet(db, tabel, gebruiker, records, bewaar_historie):
    """Records samenvoegen. De laatste schrijver wint, per RECORD.

    Per record en niet per kast: twee apparaten die elk een andere plaat
    aanpassen horen allebei te winnen. Een hele kast als eenheid behandelen is
    hoe je de aantekeningen van gisteren kwijtraakt omdat je vandaag op een
    ander apparaat iets anders aanraakte.
    """
    aangenomen, geweigerd = 0, 0
    for r in records:
        pid = str(r.get("id") or "").strip()
        if not pid:
            geweigerd += 1
            continue
        gewijzigd = str(r.get("gewijzigd") or "").strip() or nu()
        weg = 1 if r.get("weg") else 0
        doc = None if weg else json.dumps(r.get("doc") or {}, ensure_ascii=False)

        oud = db.execute(f"SELECT gewijzigd, doc FROM {tabel} "
                         "WHERE gebruiker=? AND id=?", (gebruiker, pid)).fetchone()
        if oud and oud["gewijzigd"] >= gewijzigd:
            geweigerd += 1            # wat hier staat is nieuwer; niet aanraken
            continue
        if oud and bewaar_historie and oud["doc"]:
            db.execute("INSERT INTO eigen_historie "
                       "(gebruiker, plaat, gewijzigd, vervangen, doc) VALUES (?,?,?,?,?)",
                       (gebruiker, pid, oud["gewijzigd"], nu(), oud["doc"]))
        db.execute(f"INSERT INTO {tabel} (gebruiker, id, gewijzigd, weg, doc) "
                   "VALUES (?,?,?,?,?) ON CONFLICT(gebruiker, id) DO UPDATE SET "
                   "gewijzigd=excluded.gewijzigd, weg=excluded.weg, doc=excluded.doc",
                   (gebruiker, pid, gewijzigd, weg, doc))
        aangenomen += 1
    return aangenomen, geweigerd


def duw(db, gebruiker, lichaam):
    platen = lichaam.get("platen") or []
    eigen = lichaam.get("eigen") or []
    if len(platen) + len(eigen) > MAX_RECORDS:
        raise ValueError(f"te veel records in een keer (max {MAX_RECORDS})")

    a1, w1 = _zet(db, "plaat", gebruiker, platen, False)
    a2, w2 = _zet(db, "eigen", gebruiker, eigen, True)

    naam = lichaam.get("naam")
    if naam:
        ng = str(lichaam.get("naam_gewijzigd") or nu())
        r = db.execute("SELECT gewijzigd FROM kast WHERE gebruiker=?", (gebruiker,)).fetchone()
        if not r or r["gewijzigd"] < ng:
            db.execute("INSERT INTO kast (gebruiker, naam, gewijzigd) VALUES (?,?,?) "
                       "ON CONFLICT(gebruiker) DO UPDATE SET naam=excluded.naam, "
                       "gewijzigd=excluded.gewijzigd", (gebruiker, str(naam)[:120], ng))
    db.commit()
    return {"nu": nu(), "platen": {"aangenomen": a1, "geweigerd": w1},
            "eigen": {"aangenomen": a2, "geweigerd": w2}}


# -------------------------------------------------------------------- server --

class Beheerder(SimpleHTTPRequestHandler):
    db = None
    herkomsten = ()          # extra origins die mogen meepraten (CORS)
    veilig = False           # achter TLS? dan mag het sessiekoekje Secure zijn

    def __init__(self, *a, **k):
        super().__init__(*a, directory=os.path.join(WORTEL, "site"), **k)

    def log_message(self, *a):
        pass

    # ------------------------------------------------------------- koppen --
    def end_headers(self):
        for k, v in ISOLATIE:
            self.send_header(k, v)
        if self.path.startswith("/api/"):
            self.send_header("cache-control", "no-store")
        h = self.headers.get("origin")
        if h and h in self.herkomsten:
            self.send_header("access-control-allow-origin", h)
            self.send_header("access-control-allow-credentials", "true")
            self.send_header("vary", "origin")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("access-control-allow-methods", "GET, POST, OPTIONS")
        self.send_header("access-control-allow-headers", "content-type")
        self.send_header("content-length", "0")
        self.end_headers()

    def _json(self, code, lichaam):
        rauw = json.dumps(lichaam, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(rauw)))
        self.end_headers()
        self.wfile.write(rauw)

    def _lees(self):
        n = int(self.headers.get("content-length") or 0)
        if n > MAX_LICHAAM:
            raise ValueError("bericht te groot")
        return json.loads(self.rfile.read(n) or "{}") if n else {}

    def _sessie(self):
        rauw = self.headers.get("cookie")
        if not rauw:
            return None
        try:
            c = http.cookies.SimpleCookie(rauw)
        except http.cookies.CookieError:
            return None
        return c[KOEKJE].value if KOEKJE in c else None

    def _ingelogd(self):
        r = wie(self.db, self._sessie())
        if not r:
            self._json(401, {"fout": "niet aangemeld"})
            return None
        return r

    # ---------------------------------------------------------------- GET --
    def do_GET(self):
        if self.path.startswith("/api/wie"):
            r = wie(self.db, self._sessie())
            return self._json(200, {"aangemeld": bool(r),
                                    "gebruiker": r["gebruiker"] if r else None,
                                    "naam": r["naam"] if r else None})
        if self.path.startswith("/api/haal"):
            r = self._ingelogd()
            if not r:
                return
            m = re.search(r"[?&]sinds=([^&]*)", self.path)
            sinds = urllib.parse.unquote(m.group(1)) if m else ""
            return self._json(200, haal(self.db, r["gebruiker"], sinds))
        if self.path.startswith("/api/"):
            return self._json(404, {"fout": "onbekend"})
        return super().do_GET()

    # --------------------------------------------------------------- POST --
    def do_POST(self):
        try:
            if self.path.startswith("/api/aanmelden"):
                lichaam = self._lees()
                gebruiker, geheim = meld_aan(self.db, lichaam.get("sleutel"))
                if not gebruiker:
                    # Even wachten. Niet omdat het raden hier kansrijk is - 256
                    # bits - maar omdat een server die meteen "nee" zegt een
                    # uitnodiging is om het te blijven proberen.
                    time.sleep(0.5)
                    return self._json(403, {"fout": "deze sleutel werkt niet"})
                k = http.cookies.SimpleCookie()
                k[KOEKJE] = geheim
                k[KOEKJE]["httponly"] = True
                k[KOEKJE]["path"] = "/"
                k[KOEKJE]["max-age"] = SESSIE_DAGEN * 86400
                # Van een ander domein (de site op Vercel, de server thuis) mag
                # een koekje alleen mee als het None/Secure is. Zonder TLS
                # weigert de browser die combinatie, dus dan Lax - en dan werkt
                # alleen de opstelling waarin alles van dezelfde herkomst komt.
                k[KOEKJE]["samesite"] = "None" if (self.veilig and self.herkomsten) else "Lax"
                if self.veilig:
                    k[KOEKJE]["secure"] = True
                self.send_response(200)
                self.send_header("set-cookie", k[KOEKJE].OutputString())
                rauw = json.dumps({"ok": True, "gebruiker": gebruiker}).encode()
                self.send_header("content-type", "application/json; charset=utf-8")
                self.send_header("content-length", str(len(rauw)))
                self.end_headers()
                return self.wfile.write(rauw)

            if self.path.startswith("/api/afmelden"):
                meld_af(self.db, self._sessie())
                return self._json(200, {"ok": True})

            if self.path.startswith("/api/duw"):
                r = self._ingelogd()
                if not r:
                    return
                return self._json(200, duw(self.db, r["gebruiker"], self._lees()))

            return self._json(404, {"fout": "onbekend"})
        except ValueError as e:
            return self._json(400, {"fout": str(e)})
        except Exception as e:
            return self._json(500, {"fout": f"{type(e).__name__}: {e}"})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nodig", metavar="NAAM", help="een uitnodiging maken en stoppen")
    ap.add_argument("--erbij", metavar="GEBRUIKER_ID",
                    help="nog een uitnodiging voor een BESTAANDE kast (tweede apparaat)")
    ap.add_argument("--wie", action="store_true", help="de accounts tonen en stoppen")
    ap.add_argument("--poort", type=int, default=POORT)
    ap.add_argument("--db", default=DB)
    ap.add_argument("--adres", default="127.0.0.1",
                    help="0.0.0.0 om ook op je thuisnetwerk bereikbaar te zijn")
    ap.add_argument("--herkomst", action="append", default=[],
                    help="een andere site die mag meepraten, bv https://platenkast.vercel.app")
    ap.add_argument("--veilig", action="store_true",
                    help="er zit TLS voor (tunnel of proxy): koekje als Secure")
    a = ap.parse_args()
    db = verbind(a.db)

    if a.wie:
        for g in db.execute("SELECT g.*, "
                            "(SELECT COUNT(*) FROM plaat p WHERE p.gebruiker=g.id) n, "
                            "(SELECT COUNT(*) FROM login l WHERE l.gebruiker=g.id "
                            " AND l.ingetrokken IS NULL) s "
                            "FROM gebruiker g ORDER BY g.gemaakt"):
            print(f"{g['id']}  {(g['naam'] or '-'):20} {g['n']:5} platen  "
                  f"{g['s']} sleutel(s)  sinds {g['gemaakt'][:10]}")
        return

    if a.nodig or a.erbij:
        gid, sleutel = maak_uitnodiging(db, a.nodig or "", a.erbij)
        print(f"\nkast     {gid}")
        print(f"sleutel  {sleutel}\n")
        print("Deze sleutel staat hier EEN keer. Hij is niet terug te vragen;")
        print("in de database staat alleen zijn afdruk. Kwijt? Maak een nieuwe.")
        return

    if a.adres != "127.0.0.1" and not a.veilig and not a.herkomst:
        print("Let op: geen TLS. Prima op je eigen netwerk, niet op het open internet.")

    Beheerder.db = db
    Beheerder.herkomsten = tuple(a.herkomst)
    Beheerder.veilig = a.veilig
    try:
        server = ThreadingHTTPServer((a.adres, a.poort), Beheerder)
    except OSError as e:
        sys.exit(f"Poort {a.poort} is bezet ({e}). Probeer --poort {a.poort + 1}")
    n = db.execute("SELECT COUNT(*) c FROM gebruiker").fetchone()["c"]
    print(f"Kastserver op http://{a.adres}:{a.poort}/")
    print(f"  database : {os.path.abspath(a.db)}")
    print(f"  kasten   : {n}")
    if a.herkomst:
        print(f"  ook voor : {', '.join(a.herkomst)}")
    print("\nCtrl+C om te stoppen.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nTot ziens.")


if __name__ == "__main__":
    main()
