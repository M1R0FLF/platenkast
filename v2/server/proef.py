#!/usr/bin/env python3
"""
proef.py - doet de server wat hij belooft?

    py server/proef.py

Geen framework, geen netwerk naar buiten: een database in een tijdelijke map,
een echte HTTP-server op een vrije poort, en dan de gevallen die er toe doen.

Waar dit op let
---------------
Niet of het "werkt" - dat zie je zo. Wel of de regels kloppen op de momenten
dat ze pijn doen: twee apparaten die elkaar overschrijven, een klok die
achterloopt, een sleutel die niet deugt, en de vraag of de kast van de een wel
echt onzichtbaar is voor de ander.

En een geval dat nu nog niets doet maar later alles bepaalt: een TWEEDE
uitnodiging voor dezelfde kast hoort op hetzelfde `gebruiker.id` uit te komen.
Doet hij dat niet, dan is elke sleutel stiekem een eigen account en is de
overstap naar echte accounts een datamigratie.
"""
import os, sys, json, time, shutil, tempfile, threading, urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HIER)
import kastserver as ks

GOED, FOUT = [], []


def eis(waar, wat):
    (GOED if waar else FOUT).append(wat)
    print(f"  {'ok  ' if waar else 'FOUT'}  {wat}")


class Klant:
    """Een browser: onthoudt zijn koekje, meer niet."""

    def __init__(self, basis):
        self.basis, self.koekje = basis, None

    def __call__(self, pad, lichaam=None, methode=None):
        rauw = json.dumps(lichaam).encode() if lichaam is not None else None
        v = urllib.request.Request(self.basis + pad, data=rauw,
                                   method=methode or ("POST" if rauw else "GET"))
        v.add_header("content-type", "application/json")
        if self.koekje:
            v.add_header("cookie", self.koekje)
        try:
            with urllib.request.urlopen(v, timeout=10) as a:
                k = a.headers.get("set-cookie")
                if k:
                    self.koekje = k.split(";")[0]
                return a.status, json.loads(a.read() or "{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or "{}")


def main():
    map_ = tempfile.mkdtemp(prefix="kastproef-")
    db = ks.verbind(os.path.join(map_, "proef.db"))
    ks.Beheerder.db = db
    ks.Beheerder.herkomsten = ()
    ks.Beheerder.veilig = False
    server = ThreadingHTTPServer(("127.0.0.1", 0), ks.Beheerder)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    basis = f"http://127.0.0.1:{server.server_address[1]}"
    print(f"proefserver op {basis}\n")

    try:
        # -------------------------------------------------------- aanmelden --
        print("aanmelden")
        miro, sleutel = ks.maak_uitnodiging(db, "Miro")
        anne, sleutel_anne = ks.maak_uitnodiging(db, "Anne")

        telefoon = Klant(basis)
        code, _ = telefoon("/api/aanmelden", {"sleutel": "zomaar-wat"})
        eis(code == 403, "een sleutel die niet bestaat wordt geweigerd")

        code, r = telefoon("/api/aanmelden", {"sleutel": sleutel})
        eis(code == 200 and r.get("gebruiker") == miro, "de echte sleutel meldt aan")
        eis(bool(telefoon.koekje) and sleutel not in telefoon.koekje,
            "het koekje is een sessie, niet de sleutel zelf")

        code, r = telefoon("/api/wie")
        eis(r.get("aangemeld") and r.get("naam") == "Miro", "de server weet wie je bent")

        vreemde = Klant(basis)
        code, _ = vreemde("/api/haal")
        eis(code == 401, "zonder sessie krijg je niets")

        rij = db.execute("SELECT geheim FROM login WHERE gebruiker=?", (miro,)).fetchone()
        eis(sleutel not in rij["geheim"] and len(rij["geheim"]) == 64,
            "de sleutel staat niet in de database, alleen zijn afdruk")

        # ------------------------------------------------- tweede apparaat --
        print("\ntweede apparaat op dezelfde kast")
        ook_miro, sleutel2 = ks.maak_uitnodiging(db, None, miro)
        eis(ook_miro == miro, "een tweede uitnodiging geeft DEZELFDE gebruiker")
        pc = Klant(basis)
        code, r = pc("/api/aanmelden", {"sleutel": sleutel2})
        eis(r.get("gebruiker") == miro, "en meldt aan op dezelfde kast")
        eis(db.execute("SELECT COUNT(*) c FROM gebruiker").fetchone()["c"] == 2,
            "er zijn nog steeds twee kasten, niet drie")

        # ------------------------------------------------------------ duwen --
        print("\nplaten heen en weer")
        t1 = "2026-09-18T10:00:00.000Z"
        code, r = telefoon("/api/duw", {
            "naam": "Miro's kast", "naam_gewijzigd": t1,
            "platen": [{"id": "163930", "gewijzigd": t1,
                        "doc": {"titel": "Ciao Italia '89", "prijs": 5.0}}],
            "eigen": [{"id": "163930", "gewijzigd": t1,
                       "doc": {"notitie": "van de rommelmarkt"}}],
        })
        eis(r["platen"]["aangenomen"] == 1 and r["eigen"]["aangenomen"] == 1,
            "een plaat en een aantekening komen aan")

        code, r = pc("/api/haal")
        eis(len(r["platen"]) == 1 and r["platen"][0]["doc"]["titel"] == "Ciao Italia '89",
            "het andere apparaat haalt hem op")
        eis(r["eigen"][0]["doc"]["notitie"] == "van de rommelmarkt",
            "inclusief de aantekening")
        eis(r["naam"] == "Miro's kast", "en de naam van de kast")

        code, r = pc(f"/api/haal?sinds={t1}")
        eis(r["platen"] == [] and r["eigen"] == [],
            "met `sinds` komt er niets dubbels mee")

        code, r = vreemde("/api/aanmelden", {"sleutel": sleutel_anne})
        code, r = vreemde("/api/haal")
        eis(r["platen"] == [] and r["eigen"] == [],
            "Anne ziet niets van Miro's kast")

        # ----------------------------------------------------- botsingen --
        print("\ntwee apparaten die elkaar tegenspreken")
        t0 = "2026-09-18T09:00:00.000Z"      # OUDER dan wat er staat
        t2 = "2026-09-18T11:00:00.000Z"      # nieuwer

        code, r = pc("/api/duw", {"eigen": [
            {"id": "163930", "gewijzigd": t0, "doc": {"notitie": "achterlopende klok"}}]})
        eis(r["eigen"]["geweigerd"] == 1, "een OUDERE versie wordt geweigerd")
        code, r = telefoon("/api/haal")
        eis(r["eigen"][0]["doc"]["notitie"] == "van de rommelmarkt",
            "en verandert dus niets")

        code, r = pc("/api/duw", {"eigen": [
            {"id": "163930", "gewijzigd": t2, "doc": {"notitie": "toch gekocht in Gent"}}]})
        eis(r["eigen"]["aangenomen"] == 1, "een NIEUWERE versie wint")

        h = db.execute("SELECT * FROM eigen_historie WHERE gebruiker=? AND plaat=?",
                       (miro, "163930")).fetchall()
        eis(len(h) == 1 and json.loads(h[0]["doc"])["notitie"] == "van de rommelmarkt",
            "de overschreven aantekening is bewaard, niet weg")

        # -------------------------------------------------------- weghalen --
        print("\nweghalen")
        t3 = "2026-09-18T12:00:00.000Z"
        code, r = telefoon("/api/duw", {"platen": [{"id": "163930", "gewijzigd": t3,
                                                    "weg": True}]})
        code, r = pc("/api/haal")
        eis(len(r["platen"]) == 1 and r["platen"][0].get("weg") is True,
            "een verwijdering reist mee als grafsteen, niet als stilte")
        eis("doc" not in r["platen"][0], "en neemt de inhoud niet mee")

        # ------------------------------------------------------- afmelden --
        print("\nafmelden")
        code, _ = telefoon("/api/afmelden", {})
        eis(code == 200, "afmelden lukt")
        code, _ = telefoon("/api/haal")
        eis(code == 401, "na afmelden is de sessie weg")
        code, r = pc("/api/wie")
        eis(r.get("aangemeld") is True, "maar het andere apparaat blijft aangemeld")

        # ---------------------------------------------------------- koppen --
        print("\nkoppen")
        with urllib.request.urlopen(basis + "/api/wie", timeout=10) as a:
            eis(a.headers.get("cross-origin-opener-policy") == "same-origin"
                and a.headers.get("cross-origin-embedder-policy") == "require-corp",
                "de isolatiekoppen gaan mee (anders draait de motor niet)")
    finally:
        server.shutdown()
        db.close()
        shutil.rmtree(map_, ignore_errors=True)

    print(f"\n{len(GOED)} goed, {len(FOUT)} fout")
    for f in FOUT:
        print(f"  FOUT: {f}")
    return 1 if FOUT else 0


if __name__ == "__main__":
    sys.exit(main())
