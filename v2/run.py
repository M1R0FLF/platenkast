#!/usr/bin/env python3
"""
run.py - de hele keten in een keer, met rekenwerk en netwerk naast elkaar.

Waarom dit sneller is dan v1
----------------------------
De twee knelpunten gebruiken verschillende dingen:

  uitsnijden + OCR : rekenwerk, schaalt met je kernen
  Discogs          : netwerk, hard begrensd op 60 aanroepen per minuut

In v1 waren dat losse stappen achter elkaar, dus de totale tijd was de SOM van
beide. Hier lopen ze naast elkaar en is de totale tijd de GROOTSTE van de twee.
Zodra een plaat compleet is (Miro schiet altijd voorkant, achterkant, dan
binnenwerk) gaat hij naar Discogs terwijl de volgende foto's nog gelezen
worden.

    py run.py                      alles
    py run.py --werkers 6          minder kernen gebruiken
    py run.py --vergeet            gooi de herkende platen weg en begin opnieuw
    py run.py --herlees            negeer de leescache, lees de foto's opnieuw
    py run.py --hercrop            snijd ook opnieuw uit de originelen
"""
import os, sys, json, time, queue, argparse, threading
import multiprocessing as mp

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import foto, match
from groep import Groepeerder, maak_plaat
from discogs import Discogs

KLAAR = object()


def matcher(dc, vragen, uit, slot, hoezendir, hints, zeg):
    """Draait in een draad: haalt platen uit de rij en zoekt ze op."""
    while True:
        rec = vragen.get()
        if rec is KLAAR:
            vragen.task_done()
            return
        try:
            plaat, reden = match.herken(dc, rec, hoezendir,
                                        hints.get(str(rec["id"])))
            with slot:
                if plaat:
                    uit["klaar"].append(plaat)
                    zeg("herkend", plaat=plaat, n=len(uit["klaar"]))
                else:
                    uit["rest"].append({**rec, "reden": reden})
                    zeg("onherkend", id=rec["id"], reden=reden)
        except Exception as e:                       # nooit de keten breken
            with slot:
                uit["rest"].append({**rec, "reden": f"fout: {e}"})
                zeg("onherkend", id=rec["id"], reden=f"fout: {e}")
        finally:
            vragen.task_done()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fotos", default="../platen/fotos")
    ap.add_argument("--hoezen", default="hoezen")
    ap.add_argument("--uit", default="uit")
    # Hier stond dat meer werkers TRAGER was, met cijfers erbij: 1 werker 9,5s
    # per foto, 6 werkers 13,5s. Die meting klopte; de conclusie niet.
    #
    # De oorzaak was dat onnxruntime per sessie alle kernen pakte - 46 draden
    # per proces, en RapidOCR opent drie sessies. Zes werkers waren dus 276
    # draden op 20 kernen, en die draadpoel wacht al draaiend. De regel die dat
    # had moeten voorkomen (`RapidOCR(intra_op_num_threads=1)`) deed niets; zie
    # knip._een_draad_per_sessie voor waarom. Met de draden echt vastgezet:
    #
    #    1 werker   7,55s per foto      225 foto's in 28 min
    #    4 werkers  2,93s               11 min
    #    8 werkers  2,48s                9 min
    #   16 werkers  2,03s                8 min
    #
    # Boven de acht levert het weinig meer op - dan is het geheugen aan de beurt
    # en niet de kernen meer - maar het wordt ook niet slechter.
    ap.add_argument("--werkers", type=int, default=0,
                    help="0 = zoveel als er kernen zijn, tot 12")
    ap.add_argument("--zoekers", type=int, default=2,
                    help="draden die Discogs bevragen; de snelheidsrem is gedeeld")
    ap.add_argument("--zijde", type=int, default=3200)
    ap.add_argument("--leespx", type=int, default=3200)
    ap.add_argument("--max", type=int, default=0)
    # Deze drie zaten eerst in een vlag, en daardoor gooide een test van de
    # leescache per ongeluk 77 herkende platen weg. Nu doet elke vlag een ding.
    ap.add_argument("--vergeet", action="store_true",
                    help="gooi de herkende platen weg en begin opnieuw")
    ap.add_argument("--herlees", action="store_true",
                    help="negeer de leescache en lees alle foto's opnieuw")
    ap.add_argument("--hercrop", action="store_true",
                    help="snijd de hoezen opnieuw uit de originelen")
    ap.add_argument("--stil", action="store_true")
    a = ap.parse_args()
    keten(a, printer(a.stil))


def printer(stil):
    """De meldingen zoals ze op de opdrachtregel horen te staan.

    De keten meldt gebeurtenissen; wat ermee gebeurt staat hier. Zo kan kast.py
    dezelfde keten draaien en er een voortgangsbalk van maken, zonder dat er een
    tweede kopie van de keten bestaat die stilletjes gaat afwijken.
    """
    def zeg(soort, **k):
        if soort == "melding":
            print(k["tekst"])
        elif soort == "begin":
            print(f"{k['totaal']} foto's | {k['werkers']} lezers | {k['zoekers']} zoekers | "
                  f"{k['gedaan']} platen al klaar | cache {k['cache']} aanroepen\n")
        elif soort == "herkend" and not stil:
            p = k["plaat"]
            print(f"  [{k['n']:>3}] {p['id']}  {p['bron']:<12} "
                  f"{(p['artist'] or '')[:28]} - {(p['title'] or '')[:30]}", flush=True)
        elif soort == "onherkend" and not stil:
            print(f"        {k['id']}  niet herkend: {k['reden'][:60]}", flush=True)
        elif soort == "foto" and not stil and k["klaar"] % 25 == 0:
            print(f"  ...{k['klaar']}/{k['totaal']} foto's gelezen, "
                  f"{k['platen']} platen gevormd ({k['seconden']}s)", flush=True)
        elif soort == "einde":
            d = k["duur"]
            print(f"\n{k['gelezen']} foto's -> {k['platen']} platen in {d//60}m{d%60:02d}s")
            print(f"  {k['herkend']} herkend ({k['dekking']}%), "
                  f"{k['onherkend']} met de hand -> {k['restpad']}")
            print(f"  Discogs: {k['treffers']} uit de cache, {k['missers']} opgehaald")
            print(f"\nNu:  py prijs.py {k['platenpad']} {k['csvpad']}")
    return zeg


def keten(a, melden=None, stop=None):
    """De hele keten. `melden(soort, **velden)` krijgt de voortgang,
    `stop()` mag True teruggeven om netjes af te breken."""
    zeg = melden or (lambda *x, **k: None)
    stop = stop or (lambda: False)

    os.makedirs(a.uit, exist_ok=True)
    os.makedirs(a.hoezen, exist_ok=True)
    platenpad = os.path.join(a.uit, "platen.json")
    restpad = os.path.join(a.uit, "handmatig.json")

    klaar = [] if a.vergeet else (json.load(open(platenpad, encoding="utf-8"))
                                  if os.path.exists(platenpad) else [])
    gedaan = {str(r["id"]) for r in klaar}
    hints = {}
    if os.path.exists("hints.json"):
        hints = {str(h["id"]): h for h in json.load(open("hints.json", encoding="utf-8"))}

    dc = Discogs(os.environ.get("DISCOGS_TOKEN"))
    if dc.aantal() == 0:
        n = dc.uit_json(os.path.join("..", "platen", "discogs_cache.json"))
        if n:
            zeg("melding", tekst=f"{n} bewaarde Discogs-antwoorden overgenomen uit v1")
    if not dc.token:
        zeg("melding", tekst="Geen DISCOGS_TOKEN: dit gaat ruim twee keer trager.")

    paden = foto.originelen(a.fotos)
    if a.max:
        paden = paden[:a.max]
    if not paden:
        raise SystemExit(f"Geen foto's in {a.fotos}")

    werkers = a.werkers or min(12, os.cpu_count() or 1)
    zeg("begin", totaal=len(paden), werkers=werkers, zoekers=a.zoekers,
        gedaan=len(gedaan), cache=dc.aantal(), map=os.path.abspath(a.fotos))

    uit = {"klaar": klaar, "rest": []}
    slot = threading.Lock()
    vragen = queue.Queue(maxsize=32)
    draden = [threading.Thread(target=matcher, daemon=True,
                               args=(dc, vragen, uit, slot, a.hoezen, hints, zeg))
              for _ in range(a.zoekers)]
    for d in draden:
        d.start()

    ocrcache = os.path.join("cache", "ocr.db")
    taken = [(p, a.hoezen, a.zijde, a.leespx, a.hercrop or a.herlees, ocrcache)
             for p in paden]
    t0, gelezen, platen = time.time(), 0, 0
    g = Groepeerder()

    groepen_uit = []

    def verstuur(groepen):
        nonlocal platen
        for gr in groepen:
            platen += 1
            rec = maak_plaat(gr)
            groepen_uit.append(rec)
            if str(rec["id"]) in gedaan:
                # al eerder herkend, dus geen werk meer - maar het telt wel mee
                # als plaat, anders lijkt een tweede run er nul op te leveren
                zeg("bekend", id=rec["id"])
                continue
            vragen.put(rec)

    afgebroken = False
    with mp.Pool(werkers, initializer=foto.motor) as pool:
        for res in pool.imap(foto.verwerk, taken):    # imap = op volgorde
            gelezen += 1
            if not res.get("fout"):
                verstuur(g.voeg_toe(res))
            zeg("foto", klaar=gelezen, totaal=len(paden), platen=platen,
                seconden=int(time.time() - t0))
            if stop():
                afgebroken = True
                pool.terminate()
                break
        if not afgebroken:
            verstuur(g.rest())

    vragen.join()
    for _ in draden:
        vragen.put(KLAAR)
    vragen.join()

    uit["klaar"].sort(key=lambda r: str(r["id"]))
    uit["rest"].sort(key=lambda r: str(r["id"]))
    json.dump(uit["klaar"], open(platenpad, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(uit["rest"], open(restpad, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    # de OCR per plaat bewaren, zodat controle.py kan nakijken of het
    # catalogusnummer echt op de hoes stond
    groepen_uit.sort(key=lambda r: str(r["id"]))
    json.dump(groepen_uit, open(os.path.join(a.uit, "groepen.json"), "w",
                                encoding="utf-8"), ensure_ascii=False, indent=1)

    duur = int(time.time() - t0)
    tot = platen or 1
    csvpad = os.path.join(a.uit, "platen.csv")
    zeg("einde", gelezen=gelezen, platen=platen, duur=duur,
        herkend=len(uit["klaar"]), onherkend=len(uit["rest"]),
        dekking=100 * len(uit["klaar"]) // tot, afgebroken=afgebroken,
        treffers=dc.treffers, missers=dc.missers,
        platenpad=platenpad, restpad=restpad, csvpad=csvpad)
    return {"gelezen": gelezen, "platen": platen, "herkend": len(uit["klaar"]),
            "onherkend": len(uit["rest"]), "duur": duur, "afgebroken": afgebroken,
            "platenpad": platenpad, "csvpad": csvpad}


if __name__ == "__main__":
    mp.freeze_support()
    main()
