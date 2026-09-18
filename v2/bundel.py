#!/usr/bin/env python3
"""
bundel.py - de keten klaarzetten voor de browser.

    py bundel.py

Waarom dit bestaat
------------------
De keten draait straks in Pyodide: CPython in de browser. Die haalt zijn
modules op met `fetch`, en fetchen kan alleen wat de webserver serveert. De
site-map is de wortel van die server, dus alles wat de browser moet kunnen
importeren moet daarbinnen staan.

Dit is met opzet een KOPIE en geen tweede versie. De bron blijft `v2/*.py` -
daar wordt aan gewerkt, daar draait `py run.py` op, en dat is het bestand dat
in code-review langskomt. Wat hier gekopieerd wordt is uitvoer, net als
`site/publiek/collectie.json`, en het staat dan ook in .gitignore.

Er wordt niets herschreven onderweg. Verandert er een regel in match.py, dan
verandert precies diezelfde regel in de browser. Dat is de hele reden dat de
keten naar Pyodide gaat in plaats van naar JavaScript: er is maar EEN
implementatie van "welke persing is dit", en die is gemeten.

rapidocr_onnxruntime gaat mee vanuit site-packages, maar ZONDER models/: die
drie .onnx staan al in site/motor/modellen/ en worden door onnxruntime-web
geladen, niet door Python. Ze twee keer meesturen is 14 MB voor niets.
"""
import os, sys, shutil, importlib.util

HIER = os.path.dirname(os.path.abspath(__file__))
DOEL = os.path.join(HIER, "site", "motor", "py")

BROWSER = os.path.join(HIER, "browser")   # wat alleen in de browser bestaat

# De keten. Wat hier niet in staat draait niet in de browser, en dat is een
# bewuste lijst en geen glob: kast.py, run.py en de losse gereedschappen
# (contactvel, verkooplijst, hersnij) horen bij de PC en hebben daar dingen
# nodig die een browser niet heeft - multiprocessing, argparse, een schijf.
KETEN = [
    "knip.py",      # hoes uit de foto snijden en rechtop zetten
    "foto.py",      # een foto van begin tot eind
    "groep.py",     # welke foto's horen bij dezelfde plaat
    "velden.py",    # catalogusnummer, land, jaar uit tekst
    "match.py",     # de persing vinden en verifieren
    "beeld.py",     # hoesfoto vergelijken met Discogs
    "discogs.py",   # API, snelheidsrem en cache
    "prijs.py",     # marktprijs en advertentietekst
    "nauwkeurig.py",  # het oordeel: zeker, aannemelijk, onbevestigd
    "exporteer.py",   # naar_plaat: een rij -> een plaat zoals de site hem kent
    # Ronde twee. Zonder deze twee raadt de browser de rand en de draaiing, en
    # dan is de uitsnede - en dus de tekst - een andere dan op de pc.
    "beeldtoets.py",  # cover_urls: welke afbeeldingen een hoes kunnen zijn
    "hersnij.py",     # de hoes op Discogs als mal, en de vierhoek opmeten
]


def kopieer_keten():
    n = 0
    for naam in KETEN:
        bron = os.path.join(HIER, naam)
        if not os.path.exists(bron):
            sys.exit(f"ontbreekt: {naam}")
        shutil.copy2(bron, os.path.join(DOEL, naam))
        n += 1
    return n


# Wat er alleen in de browser is. Staat in `v2/browser/` en niet hiernaast,
# want het is broncode en `py/` is uitvoer.
#
# Hier stond eerst "alles in die map gaat mee", met als reden dat er dan niet
# nog een lijst is die kan gaan afwijken. Die reden was goed zolang er in die
# map alleen browserkant stond. Inmiddels staan er ook meetscripts (`ijk*.py`)
# en een eenmalige reparatie (`herstel163930.py`), en die gingen dus mee: elke
# telefoon die de site opent haalde een script op dat bestanden op EEN schijf
# ergens wil bijwerken. Niet gevaarlijk, wel onzin.
#
# Dus toch een lijst. Wijkt hij af, dan valt dat meteen op, want dan ontbreekt
# er een module en start de motor niet.
BROWSERKANT = [
    "ocr_brug.py",      # vervangt OrtInferSession door onnxruntime-web
    "plaat.py",         # de keten voor EEN plaat, zoals de motor hem aanroept
]


def kopieer_browserkant():
    n = 0
    for naam in BROWSERKANT:
        bron = os.path.join(BROWSER, naam)
        if not os.path.exists(bron):
            sys.exit(f"ontbreekt: browser/{naam}")
        shutil.copy2(bron, os.path.join(DOEL, naam))
        n += 1
    # Wat er ooit wel in stond hoort er ook weer uit, anders blijft het op de
    # gepubliceerde site staan tot iemand het toevallig ziet.
    for naam in sorted(os.listdir(DOEL)):
        if naam.endswith(".py") and naam not in BROWSERKANT and naam not in KETEN:
            os.remove(os.path.join(DOEL, naam))
            print(f"  opgeruimd: {naam}")
    return n


def kopieer_rapidocr():
    """Het OCR-pakket, zonder de modellen.

    Zonder deze kopie zou de browser `pip install rapidocr-onnxruntime` moeten
    doen via micropip, en dat trekt de 14 MB modellen er nog een keer bij -
    terwijl onnxruntime-web ze al apart laadt.
    """
    s = importlib.util.find_spec("rapidocr_onnxruntime")
    if s is None:
        sys.exit("rapidocr_onnxruntime staat niet op deze pc - eerst "
                 "`pip install -r vereisten.txt`")
    bron = os.path.dirname(s.origin)
    doel = os.path.join(DOEL, "rapidocr_onnxruntime")
    if os.path.exists(doel):
        shutil.rmtree(doel)
    shutil.copytree(bron, doel, ignore=shutil.ignore_patterns(
        "models", "__pycache__", "*.pyc"))
    return sum(len(f) for _, _, f in os.walk(doel))


def lijst():
    """Wat de browser moet ophalen, en in welke map het hoort.

    De Pyodide-worker leest dit in plaats van zelf te raden: een map
    doorzoeken kan een browser niet, dus de serverkant moet vertellen wat er
    ligt. Verandert KETEN, dan verandert dit bestand mee.
    """
    uit = []
    for wortel, _, bestanden in os.walk(DOEL):
        for b in sorted(bestanden):
            if b.endswith(".py") or b.endswith(".yaml"):
                p = os.path.relpath(os.path.join(wortel, b), DOEL)
                uit.append(p.replace("\\", "/"))
    return uit


def main():
    os.makedirs(DOEL, exist_ok=True)
    n = kopieer_keten()
    b = kopieer_browserkant()
    m = kopieer_rapidocr()
    bestanden = lijst()

    import json
    with open(os.path.join(DOEL, "bestanden.json"), "w", encoding="utf-8") as fh:
        json.dump(bestanden, fh, indent=1)

    mb = sum(os.path.getsize(os.path.join(w, b))
             for w, _, bs in os.walk(DOEL) for b in bs) / 1e6
    print(f"{n} ketenbestanden + {b} browserkant + rapidocr ({m} bestanden)"
          f" -> site/motor/py/")
    print(f"{len(bestanden)} modules, samen {mb:.2f} MB")


if __name__ == "__main__":
    main()
