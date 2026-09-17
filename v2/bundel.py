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


def kopieer_browserkant():
    """Wat er alleen in de browser is: de brug naar onnxruntime-web.

    Staat in `v2/browser/` en niet hiernaast, want het is broncode en `py/`
    is uitvoer. Alles in die map gaat mee, zodat er niet nog een lijst is die
    kan gaan afwijken.
    """
    n = 0
    for naam in sorted(os.listdir(BROWSER)):
        if naam.endswith(".py"):
            shutil.copy2(os.path.join(BROWSER, naam), os.path.join(DOEL, naam))
            n += 1
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
