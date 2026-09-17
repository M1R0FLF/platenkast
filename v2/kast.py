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
import os, re, sys, json, time, queue, threading, argparse, webbrowser
import multiprocessing as mp
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HIER)

POORT = 7385

# Zonder deze twee koppen geen SharedArrayBuffer, en zonder SharedArrayBuffer
# draait de keten niet in de browser: Pyodide roept de OCR synchroon aan en
# onnxruntime-web antwoordt asynchroon, dus de twee moeten elkaar over gedeeld
# geheugen vinden. Zie site/static/motor/ort-werker.js.
#
# Dezelfde isolatie zet ook WASM-threads aan. Dat is geen bijvangst maar de
# reden dat het op een telefoon te doen is: zonder threads rekent onnxruntime
# op een kern.
#
# Prijs: alles van een ander domein moet CORP of CORS meesturen. jsdelivr doet
# dat (`cross-origin-resource-policy: cross-origin` op elk bestand), en verder
# haalt deze site niets van buiten. Vercel stuurt dezelfde koppen; zie
# site/vercel.json, want die twee moeten gelijk blijven.
ISOLATIE = [
    ("cross-origin-opener-policy", "same-origin"),
    ("cross-origin-embedder-policy", "require-corp"),
]


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

            # ---- de uitsnedes rechtop, nu de persing bekend is ----
            # Moet hier en niet eerder: knip.rechtop moet raden zolang er niets
            # van de plaat bekend is, en raadde 22 procent van de voorkanten
            # verkeerd. Met de hoes van Discogs ernaast is het een meting.
            if not self.afbreken:
                import stand
                self.zend("fase", naam="rechtzetten", totaal=len(platen))
                gedraaid = [0]

                def uit_stand(pid, slot, k, g, n):
                    if pid == "voortgang":
                        self.zend("rechtzetten", klaar=slot, totaal=k,
                                  gedraaid=gedraaid[0])
                    elif k:
                        gedraaid[0] += 1

                standuit = stand.loop(platen, self.hoezen, dc, False, uit_stand)
                # De duimnagel van een gedraaide uitsnede staat er nog scheef
                # bij, en duimnagels() slaat bestaande bestanden over. Dus weg
                # ermee; de volgende stap maakt ze opnieuw.
                duim = os.path.join(self.sitemap, "publiek", "duim")
                for u in standuit:
                    if not u["gedraaid"]:
                        continue
                    oud = os.path.join(duim, f"{u['id']}-{u['slot']}.jpg")
                    if os.path.exists(oud):
                        os.remove(oud)

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


def _release_id(tekst):
    """Het nummer uit wat je plakt: een hele Discogs-URL mag, het kale getal ook.

    discogs.com/release/34612549-ABBA-Under-Attack -> 34612549
    [r34612549] (zo schrijft Discogs het zelf in fora)  -> 34612549
    """
    tekst = (tekst or "").strip()
    m = re.search(r"/release/(\d+)", tekst) or re.search(r"\[r(\d+)\]", tekst)
    if m:
        return int(m.group(1))
    return int(tekst) if tekst.isdigit() else None


def kies_map(begin=None):
    """Een echte mapkiezer van Windows zelf.

    Een pad overtypen uit de verkenner is de onvriendelijkste stap die er was,
    en de browser mag ons geen pad geven (alleen bestanden). Deze server draait
    op jouw machine, dus die mag het wel vragen.
    """
    try:
        import tkinter
        from tkinter import filedialog
    except ImportError:
        return None, "tkinter ontbreekt in deze Python"
    try:
        wortel = tkinter.Tk()
        wortel.withdraw()
        wortel.attributes("-topmost", True)    # anders verdwijnt hij achter de browser
        pad = filedialog.askdirectory(title="Map met foto's kiezen",
                                      initialdir=begin or os.path.expanduser("~"))
        wortel.destroy()
        return (pad or None), None
    except Exception as e:
        return None, str(e)


def bekijk_release(release_id, rec, hoezendir):
    """Wat staat er op deze release, en lijkt de hoes erop?

    Dit gaat VOOR het vastleggen, want een link plakken is even makkelijk fout
    als goed. Bij het testen werd een verkeerd release-nummer klakkeloos
    "Gorillaz - Plastic Beach" onder een Streisand-hoes, zonder een kik. De hele
    keten is gebouwd op "liever niets dan het verkeerde"; dan mag de handmatige
    ingang niet het enige gat in die regel zijn.

    Het blijft jouw beslissing - je krijgt alleen te zien waar je ja op zegt.
    """
    import match
    from discogs import Discogs
    dc = Discogs(os.environ.get("DISCOGS_TOKEN"))
    rel = dc.release(int(release_id))
    if not rel:
        raise ValueError(f"release {release_id} niet gevonden op Discogs")
    punten = match.beeld_punten(dc, rec, rel["id"], hoezendir)
    afbeelding = next((i.get("uri") for i in (rel.get("images") or []) if i.get("uri")), None)
    return rel, {
        "titel": rel.get("title"),
        "artiest": ", ".join(a["name"] for a in (rel.get("artists") or []))[:120],
        "jaar": rel.get("year"),
        "land": rel.get("country"),
        "catno": (rel.get("labels") or [{}])[0].get("catno"),
        "formaat": "; ".join(f"{f.get('qty')}x {f.get('name')} "
                             f"{' '.join(f.get('descriptions') or [])}".strip()
                             for f in (rel.get("formats") or [])),
        "afbeelding": afbeelding,
        "beeld_punten": punten,
        # None = niets te vergelijken. Dat is geen goedkeuring en ook geen afkeuring.
        "hoes_klopt": None if punten is None else punten >= match.BEELD_FOUT,
    }


def voeg_handmatig_toe(release_id, rec, uitmap, hoezendir, rel=None):
    """Een onherkende plaat alsnog vastleggen, op een release die JIJ aanwijst.

    Dit is geen gok van de machine: het id komt van jou. Daarom mag dit langs de
    automatische verificatie heen - die is er om te voorkomen dat de MACHINE
    iets verzint, niet om jou tegen te spreken.
    """
    import match
    from discogs import Discogs
    dc = Discogs(os.environ.get("DISCOGS_TOKEN"))
    rel = rel or dc.release(int(release_id))
    if not rel:
        raise ValueError(f"release {release_id} niet gevonden op Discogs")
    titels = [t["title"] for t in (rel.get("tracklist") or []) if t.get("title")]
    plaat = match._plaat(rec, rel, titels, "door jou aangewezen", "handmatig")
    plaat["beeld_punten"] = match.beeld_punten(dc, rec, rel["id"], hoezendir)

    platenpad = os.path.join(uitmap, "platen.json")
    restpad = os.path.join(uitmap, "handmatig.json")
    platen = json.load(open(platenpad, encoding="utf-8")) if os.path.exists(platenpad) else []
    platen = [p for p in platen if str(p["id"]) != str(plaat["id"])] + [plaat]
    platen.sort(key=lambda r: str(r["id"]))
    json.dump(platen, open(platenpad, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    rest = json.load(open(restpad, encoding="utf-8")) if os.path.exists(restpad) else []
    rest = [r for r in rest if str(r["id"]) != str(plaat["id"])]
    json.dump(rest, open(restpad, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return plaat


def _kan_publiceren(sitemap):
    """Alleen aanbieden als er ook echt iets is om naar te publiceren: een
    git-map MET een remote. Een knop die altijd faalt is erger dan geen knop."""
    import subprocess
    wortel = os.path.dirname(os.path.dirname(os.path.abspath(sitemap)))
    try:
        r = subprocess.run(["git", "remote"], cwd=wortel, capture_output=True,
                           text=True, timeout=10)
        return r.returncode == 0 and bool(r.stdout.strip())
    except Exception:
        return False


def publiceer(sitemap):
    """site/publiek naar GitHub duwen; Vercel bouwt daarna vanzelf opnieuw.

    Alleen de gegevens van de site, niet de rest van de map: een run raakt ook
    caches en uitvoerbestanden aan en die horen niet in een publicatie.
    """
    import subprocess
    wortel = os.path.dirname(os.path.dirname(os.path.abspath(sitemap)))

    def git(*args):
        return subprocess.run(["git"] + list(args), cwd=wortel, capture_output=True,
                              text=True, timeout=180)

    if git("rev-parse", "--git-dir").returncode:
        raise RuntimeError("dit is geen git-map, dus er is niets om naar te publiceren")
    doel = os.path.relpath(os.path.join(sitemap, "publiek"), wortel).replace("\\", "/")
    git("add", "--", doel)
    if not git("diff", "--cached", "--quiet", "--", doel).returncode:
        return "de website is al bij"
    c = git("commit", "-m", f"Kast bijgewerkt: {time.strftime('%Y-%m-%d %H:%M')}")
    if c.returncode:
        raise RuntimeError(f"commit mislukt: {(c.stderr or c.stdout)[:300]}")
    p = git("push")
    if p.returncode:
        raise RuntimeError(f"push mislukt: {(p.stderr or p.stdout)[:300]}")
    return "gepubliceerd - Vercel zet het er binnen een minuut op"


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

    def end_headers(self):
        """Lokaal niets bewaren behalve de duimnagels.

        Zonder dit serveert de browser na een wijziging vrolijk de oude app.js
        door - en dan zoek je een fout die allang weg is. Duimnagels mogen wel
        blijven staan: die veranderen alleen als de foto verandert, en dan
        krijgen ze toch een andere naam.
        """
        if not self.path.startswith("/publiek/duim/"):
            self.send_header("cache-control", "no-store, must-revalidate")
        for k, v in ISOLATIE:
            self.send_header(k, v)
        super().end_headers()

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
                                    "token": bool(os.environ.get("DISCOGS_TOKEN")),
                                    "kan_publiceren": _kan_publiceren(m.sitemap)})
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

        if self.path.startswith("/api/kies-map"):
            pad, fout = kies_map(m.fotos)
            if fout:
                return self._json(500, {"fout": fout})
            return self._json(200, {"map": pad})

        if self.path.startswith("/api/handmatig"):
            if m.draait:
                return self._json(409, {"fout": "er draait een run"})
            try:
                lichaam = self._lees_json()
                rid = _release_id(lichaam.get("release") or "")
                if not rid:
                    raise ValueError("geen release-id gevonden in wat je plakte")
                restpad = os.path.join(m.uitmap, "handmatig.json")
                rest = json.load(open(restpad, encoding="utf-8"))
                rec = next((r for r in rest if str(r["id"]) == str(lichaam.get("id"))), None)
                if rec is None:
                    raise ValueError("die plaat staat niet meer op de handmatige lijst")
                rel, blik = bekijk_release(rid, rec, m.hoezen)
                # Eerst laten zien wat je aanwijst. Pas bij de tweede aanroep,
                # met bevestigd=true, gaat het de kast in.
                if not lichaam.get("bevestigd"):
                    return self._json(200, {"ok": False, "voorbeeld": blik})
                plaat = voeg_handmatig_toe(rid, rec, m.uitmap, m.hoezen, rel)
                import prijs, exporteer
                from discogs import Discogs
                platen = json.load(open(os.path.join(m.uitmap, "platen.json"),
                                        encoding="utf-8"))
                rijen = prijs.prijzen(platen, Discogs(os.environ.get("DISCOGS_TOKEN")),
                                      os.path.join(HIER, "lookup_cache.json"))
                prijs.schrijf_csv(rijen, os.path.join(m.uitmap, "platen.csv"))
                doc = m._exporteer(exporteer)
                return self._json(200, {"ok": True, "plaat": plaat, "collectie": doc})
            except Exception as e:
                return self._json(400, {"fout": f"{type(e).__name__}: {e}"})

        if self.path.startswith("/api/publiceer"):
            try:
                return self._json(200, {"ok": True, "bericht": publiceer(m.sitemap)})
            except Exception as e:
                return self._json(400, {"fout": str(e)})

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
