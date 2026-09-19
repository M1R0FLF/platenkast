"""
ijkdrift.py - maakt de OCR-drift verschil voor de PERSING?

    py browser/ijkdrift.py [aantal]      het ijkpunt op de PC maken

De vorige proef gaf beide kanten dezelfde tekst en kreeg 20 van de 20 dezelfde
persing. Daarmee staat vast dat match.py zich in Pyodide gedraagt zoals op de
PC. Wat er NIET mee vaststaat is of het uitmaakt dat de browser de hoes net
anders leest - 28 van de 35 regels gelijk, zeven die in een spatie verschillen.

Dat is geen detail. `velden.tracktermen` neemt alleen regels met een spatie
erin, want waar RapidOCR niet geplakt heeft is het leesbaar. Precies die regels
verschillen. Op een hoes met een leesbaar catalogusnummer maakt het niets uit -
dat nummer is in beide gelijk - maar juist de moeilijke hoezen hebben dat
nummer niet, en leunen op tracktitels.

Waarom dit een gedeelde module is
---------------------------------
`draai()` draait op de PC en in de browser, uit hetzelfde bestand. Zou ik de
twee kanten los schrijven, dan meet ik behalve de drift ook het verschil tussen
mijn twee versies, en dan zegt een afwijking niets.

De beeldronde staat uit (lege hoezenmap), net als in ijkmatch.py, om dezelfde
reden: een verschil moet aan een ding toe te schrijven zijn.
"""
import os, sys, json

HIER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HIER not in sys.path:
    sys.path.insert(0, HIER)


def lees_foto(pad, naam, bestand):
    """Een foto lezen zoals foto.py dat doet, maar zonder schijf en cache.

    Gebruikt `foto._vakken`, dus de vakindeling en de sortering komen uit de
    keten zelf en niet uit een kopie die kan gaan afwijken.

    De hoezen in `hoezen/` liggen al op zijde 2400: groter dan de 1800 px
    waarop `foto._verwerk` leest voor hij het aan de OCR geeft. Zonder deze
    schaling leest de PC de volle 2400 (dat kan, onbeperkt geheugen) en de
    browser niets: `ocr_brug` past de foto in een vaste brug van enkele
    tientallen MB en weigert wat er niet in past. Dat leek eerst "de browser
    leest deze hoezen niet", en was gewoon deze stap die miste.
    """
    import cv2, foto
    img = cv2.imread(pad, cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(pad)
    f = 1800 / max(img.shape[:2])
    if f < 1:
        img = cv2.resize(img, (int(img.shape[1] * f), int(img.shape[0] * f)),
                         interpolation=cv2.INTER_AREA)
    vakken = foto._vakken(img)
    return {"naam": naam, "bestand": bestand, "vakken": vakken,
            "t": "\n".join(v["t"] for v in vakken),
            # De hoekstrook blijft leeg, aan BEIDE kanten. Die komt bij foto.py
            # uit een aparte uitsnede van de rug, en die stap hoort niet in deze
            # meting thuis - hij zou er alleen ruis aan toevoegen.
            "h": ""}


def draai(platen, dc, hoezendir, melden=None):
    """Foto's -> record -> persing, voor een rij platen.

    `platen` is [{"id":..., "fotos":[{"pad","naam","bestand"},...]}, ...].
    Geeft per plaat de gekozen release terug, plus het record zelf zodat je
    kunt zien WAAROM twee kanten uit elkaar lopen.
    """
    import match
    from groep import maak_plaat

    uit = []
    for i, p in enumerate(platen, 1):
        try:
            fotos = [lees_foto(f["pad"], f["naam"], f["bestand"]) for f in p["fotos"]]
            rec = maak_plaat(fotos)
            plaat, reden = match.herken(dc, rec, hoezendir)
            uit.append({"id": rec["id"],
                        "release": plaat.get("release_id_auto") if plaat else None,
                        "reden": reden,
                        "catno": rec.get("catno_kandidaten"),
                        "tracktermen": __import__("velden").tracktermen(rec),
                        "tekst": rec.get("ocr_achterkant", "")[:600]})
        except Exception as e:
            uit.append({"id": p["id"], "release": None,
                        "reden": f"fout: {type(e).__name__}: {e}"})
        if melden:
            melden(i, len(platen), uit[-1])
    return uit


# ------------------------------------------------------------------- PC-kant --

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("aantal", nargs="?", type=int, default=10)
    a = ap.parse_args()
    os.chdir(HIER)

    from discogs import Discogs

    groepen = json.load(open("uit/groepen.json", encoding="utf-8"))
    doelmap = os.path.join(HIER, "site", "motor", "ijk", "drift")
    os.makedirs(doelmap, exist_ok=True)

    # Alleen platen waarvan beide foto's er nog zijn; een halve plaat meten
    # zegt niets.
    bruikbaar = []
    for g in groepen:
        paden = [os.path.join("hoezen", b) for b in g["fotos"][:2]]
        if all(os.path.exists(p) for p in paden):
            bruikbaar.append((g, paden))
    stap = max(1, len(bruikbaar) // a.aantal)
    keuze = bruikbaar[::stap][:a.aantal]
    print(f"{len(bruikbaar)} platen met beide foto's, {len(keuze)} gekozen\n")

    import shutil
    platen, mee = [], 0
    for g, paden in keuze:
        fotos = []
        for p in paden:
            b = os.path.basename(p)
            shutil.copy2(p, os.path.join(doelmap, b))
            mee += os.path.getsize(p)
            fotos.append({"pad": p, "naam": os.path.splitext(b)[0], "bestand": b})
        platen.append({"id": g["id"], "fotos": fotos})

    dc = Discogs(os.environ.get("DISCOGS_TOKEN"))
    gebruikt = {}
    echt_lees, echt_schrijf = dc._lees, dc._schrijf

    def lees(s):
        w = echt_lees(s)
        if w is not None:
            gebruikt[s] = w
        return w

    def schrijf(s, w):
        gebruikt[s] = w
        return echt_schrijf(s, w)

    dc._lees, dc._schrijf = lees, schrijf

    leeg = os.path.join(HIER, "uit", "_geen_hoezen")
    os.makedirs(leeg, exist_ok=True)

    def melden(i, n, r):
        print(f"  {i:3}/{n}  {str(r['id']):8} {str(r['release'] or '-'):10} "
              f"{(r.get('reden') or '')[:46]}", flush=True)

    uit = draai(platen, dc, leeg, melden)

    # De browser roept straks `import ijkdrift` aan (zie py-werker.js), en
    # bundel.py stuurt dit bestand met opzet NIET mee naar de gewone bundel -
    # het is meetgereedschap, geen ketencode. Dus komt het hier, naast de
    # data die het nodig heeft, in een map die alleen de proefpagina leest.
    shutil.copy2(os.path.abspath(__file__),
                 os.path.join(HIER, "site", "motor", "ijk", "ijkdrift.py"))

    doel = os.path.join(HIER, "site", "motor", "ijk", "drift.json")
    with open(doel, "w", encoding="utf-8") as fh:
        json.dump({"platen": [{"id": p["id"],
                               "fotos": [{"naam": f["naam"], "bestand": f["bestand"]}
                                         for f in p["fotos"]]} for p in platen],
                   "verwacht": uit, "cache": gebruikt}, fh, ensure_ascii=False)

    print(f"\n{sum(1 for u in uit if u['release'])} van de {len(uit)} herkend")
    print(f"{len(gebruikt)} Discogs-sleutels, {mee / 1e6:.0f} MB foto's "
          f"-> site/motor/ijk/drift/")


if __name__ == "__main__":
    main()
