#!/usr/bin/env python3
"""
kast.py - de site op je eigen computer, met de keten eronder.

    py kast.py                     opent de kast in je browser
    py kast.py --fotos D:\\platen   met een andere map foto's
    py kast.py --poort 7390        als 7385 al bezet is

Waarom dit bestaat
------------------
De gepubliceerde site kan alles behalve het zware werk: een hoes uitsnijden en
lezen kost negen seconden, en tweehonderd foto's zijn dus een half uur
rekenwerk. Dat hoort op de machine waar de foto's al staan, niet bij een
webhost die per seconde afrekent.

Dit is daarom precies dezelfde site - zelfde bestanden, zelfde schermen - met
er een paar endpoints naast die de keten aansturen en hun voortgang doorgeven.
Zodra dit draait ziet het tabblad "Verwerken" een motor en verandert de uitleg
in een knop.

Er wordt met opzet alleen naar 127.0.0.1 geluisterd. Dit is geen server voor
anderen: het draait als jou, met toegang tot jouw schijf.
"""
import os, sys, json, time, queue, threading, argparse, webbrowser
import multiprocessing as mp
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HIER)

POORT = 7385


class Motor:
    """Eén run tegelijk, met een rij abonnees die de voortgang meelezen."""

    def __init__(self, fotos, hoezen, uitmap, sitemap):
        self.fotos, self.hoezen = fotos, hoezen
        self.uitmap, self.sitemap = uitmap, sitemap
        self.draait = False
        self.afbreken = False
        self.abonnees = []
        self.slot = threading.Lock()

    # ---------------------------------------------------------- doorgeven --
    def abonneer(self):
        q = queue.Queue()
        with self.slot:
            self.abonnees.append(q)
        return q

    def zeg_af(self, q):
        with self.slot:
            if q in self.abonnees:
                self.abonnees.remove(q)

    def zend(self, soort, **velden):
        bericht = json.dumps({"soort": soort, **velden}, ensure_ascii=False, default=str)
        with self.slot:
            for q in list(self.abonnees):
                q.put(bericht)

    # ----------------------------------------------------------- draaien --
    def start(self, fotomap=None):
        if self.draait:
            raise RuntimeError("er draait al een run")
        self.fotos = fotomap or self.fotos
        if not os.path.isdir(self.fotos):
            raise FileNotFoundError(f"map bestaat niet: {self.fotos}")
        self.draait, self.afbreken = True, False
        threading.Thread(target=self._draai, daemon=True).start()

    def _draai(self):
        import run, prijs, exporteer
        from discogs import Discogs
        t0 = time.time()
        waarde = [0.0]
        try:
            opties = argparse.Namespace(
                fotos=self.fotos, hoezen=self.hoezen, uit=self.uitmap,
                werkers=0, zoekers=2, zijde=3200, leespx=3200, max=0,
                vergeet=False, herlees=False, hercrop=False, stil=True)

            def uit_keten(soort, **k):
                if soort == "begin":
                    self.zend("start", totaal=k["totaal"], map=k["map"])
                    self.zend("fase", naam="lezen", totaal=k["totaal"])
                elif soort == "foto":
                    self.zend("voortgang", klaar=k["klaar"], totaal=k["totaal"],
                              resterend=_resterend(t0, k["klaar"], k["totaal"]))
                elif soort == "herkend":
                    p = k["plaat"]
                    self.zend("herkend", n=k["n"], artiest=p.get("artist"),
                              titel=p.get("title"))
                elif soort == "bekend":
                    self.zend("bekend", id=k["id"])
                elif soort == "onherkend":
                    self.zend("onherkend", id=k["id"], reden=k["reden"])
                elif soort == "melding":
                    self.zend("melding", tekst=k["tekst"])

            uitslag = run.keten(opties, uit_keten, lambda: self.afbreken)

            # ---- tweede fase: persing en prijs ----
            platen = json.load(open(uitslag["platenpad"], encoding="utf-8"))
            self.zend("fase", naam="prijzen", totaal=len(platen))
            t1 = time.time()

            def uit_prijs(soort, **k):
                if soort != "prijs":
                    return
                r = k["rij"]
                p = r.get("vraagprijs")
                waarde[0] += float(p or 0)
                self.zend("prijs", klaar=k["klaar"], totaal=k["totaal"],
                          artiest=r.get("artiest_discogs") or r.get("gelezen_artist"),
                          titel=r.get("titel_discogs") or r.get("gelezen_title"),
                          prijs=p, waarde=round(waarde[0], 2),
                          resterend=_resterend(t1, k["klaar"], k["totaal"]))

            dc = Discogs(os.environ.get("DISCOGS_TOKEN"))
            rijen = prijs.prijzen(platen, dc, os.path.join(HIER, "lookup_cache.json"),
                                  uit_prijs, lambda: self.afbreken)
            prijs.schrijf_csv(rijen, uitslag["csvpad"])

            # ---- derde fase: duimnagels en collectie.json ----
            self.zend("fase", naam="samenstellen", totaal=len(rijen))
            self._exporteer(exporteer)

            self.zend("klaar", platen=len(rijen), waarde=round(waarde[0], 2),
                      afgebroken=self.afbreken,
                      duur=int(time.time() - t0))
        except Exception as e:
            self.zend("fout", bericht=f"{type(e).__name__}: {e}")
            self.zend("klaar", platen=0, waarde=0, afgebroken=True, duur=0)
        finally:
            self.draait = False

    def _exporteer(self, exporteer):
        platen, handmatig = exporteer.bouw(
            os.path.join(self.uitmap, "platen.csv"),
            os.path.join(self.uitmap, "platen.json"),
            os.path.join(self.uitmap, "groepen.json"),
            os.path.join(self.uitmap, "handmatig.json"))
        publiek = os.path.join(self.sitemap, "publiek")
        exporteer.duimnagels(platen + handmatig, self.hoezen,
                             os.path.join(publiek, "duim"))
        telling = {}
        for p in platen:
            telling[p["oordeel"]] = telling.get(p["oordeel"], 0) + 1
        doc = {"versie": 1, "naam": "Mijn platenkast", "platen": platen,
               "handmatig": handmatig,
               "samenvatting": {"platen": len(platen), "onherkend": len(handmatig),
                                "met_prijs": sum(1 for p in platen if p["prijs"]),
                                "waarde": round(sum(p["prijs"] or 0 for p in platen), 2),
                                "oordeel": telling}}
        os.makedirs(publiek, exist_ok=True)
        with open(os.path.join(publiek, "collectie.json"), "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, separators=(",", ":"))
        return doc


def _resterend(t0, klaar, totaal):
    """Een schatting die pas iets zegt als er genoeg gemeten is. De eerste
    foto's zijn traag (de modellen moeten nog laden), dus eerder schatten
    levert een getal op dat binnen tien seconden onzin blijkt."""
    if klaar < 4 or klaar >= totaal:
        return ""
    per = (time.time() - t0) / klaar
    s = int(per * (totaal - klaar))
    return f"{s // 60}m{s % 60:02d}s" if s >= 60 else f"{s}s"


class Beheerder(SimpleHTTPRequestHandler):
    motor = None

    def __init__(self, *a, **k):
        super().__init__(*a, directory=os.path.join(HIER, "site"), **k)

    def log_message(self, *a):
        pass                                   # de keten praat al genoeg

    # ------------------------------------------------------------ helpers --
    def _json(self, code, lichaam):
        rauw = json.dumps(lichaam, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(rauw)))
        self.send_header("cache-control", "no-store")
        self.end_headers()
        self.wfile.write(rauw)

    def _lees_json(self):
        n = int(self.headers.get("content-length") or 0)
        return json.loads(self.rfile.read(n) or "{}") if n else {}

    # --------------------------------------------------------------- GET --
    def do_GET(self):
        m = self.motor
        if self.path.startswith("/api/status"):
            return self._json(200, {"versie": 1, "draait": m.draait,
                                    "fotomap": os.path.abspath(m.fotos),
                                    "token": bool(os.environ.get("DISCOGS_TOKEN"))})
        if self.path.startswith("/api/collectie"):
            pad = os.path.join(HIER, "site", "publiek", "collectie.json")
            if not os.path.exists(pad):
                return self._json(404, {"fout": "nog geen collectie"})
            with open(pad, encoding="utf-8") as fh:
                return self._json(200, json.load(fh))
        if self.path.startswith("/api/stroom"):
            return self._stroom()
        return super().do_GET()

    def _stroom(self):
        self.send_response(200)
        self.send_header("content-type", "text/event-stream; charset=utf-8")
        self.send_header("cache-control", "no-cache")
        self.send_header("connection", "keep-alive")
        self.end_headers()
        q = self.motor.abonneer()
        try:
            while True:
                try:
                    bericht = q.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b": leeft nog\n\n")   # anders sluit de proxy
                    self.wfile.flush()
                    continue
                self.wfile.write(f"data: {bericht}\n\n".encode("utf-8"))
                self.wfile.flush()
                if '"soort": "klaar"' in bericht or '"soort":"klaar"' in bericht:
                    break
        except (BrokenPipeError, ConnectionResetError):
            pass                                  # tabblad dicht, ook goed
        finally:
            self.motor.zeg_af(q)

    # -------------------------------------------------------------- POST --
    def do_POST(self):
        m = self.motor
        if self.path.startswith("/api/start"):
            try:
                lichaam = self._lees_json()
                m.start((lichaam.get("map") or "").strip() or None)
                return self._json(200, {"ok": True, "map": os.path.abspath(m.fotos)})
            except Exception as e:
                return self._json(400, {"fout": str(e)})
        if self.path.startswith("/api/stop"):
            m.afbreken = True
            return self._json(200, {"ok": True})
        return self._json(404, {"fout": "onbekend"})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fotos", default=os.path.join("..", "platen", "fotos"))
    ap.add_argument("--hoezen", default="hoezen")
    ap.add_argument("--uit", default="uit")
    ap.add_argument("--poort", type=int, default=POORT)
    ap.add_argument("--stil", action="store_true", help="browser niet openen")
    a = ap.parse_args()

    os.chdir(HIER)                    # de keten rekent met paden vanaf hier
    Beheerder.motor = Motor(a.fotos, a.hoezen, a.uit, os.path.join(HIER, "site"))

    try:
        server = ThreadingHTTPServer(("127.0.0.1", a.poort), Beheerder)
    except OSError as e:
        sys.exit(f"Poort {a.poort} is bezet ({e}). Probeer: py kast.py --poort {a.poort + 1}")

    url = f"http://127.0.0.1:{a.poort}/"
    print(f"Platenkast draait op {url}")
    print(f"  foto's : {os.path.abspath(a.fotos)}")
    print(f"  token  : {'ja' if os.environ.get('DISCOGS_TOKEN') else 'nee - geen prijzen'}")
    print("\nCtrl+C om te stoppen.")
    if not a.stil:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nTot ziens.")


if __name__ == "__main__":
    mp.freeze_support()
    main()
