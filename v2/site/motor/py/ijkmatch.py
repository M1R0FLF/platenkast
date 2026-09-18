#!/usr/bin/env python3
"""
ijkmatch.py - het ijkpunt voor `match.herken` in de browser.

    py browser/ijkmatch.py [aantal]

Wat dit maakt
-------------
`site/motor/ijk/match.json`: een stel platen uit `uit/groepen.json`, het
antwoord dat de PC erop geeft, EN elke Discogs-aanroep die daarvoor nodig was.

Dat laatste is de kern. Zonder meegeleverde cache zou de browser dezelfde vraag
opnieuw aan Discogs stellen, en dan meet je drie dingen tegelijk: de logica, het
netwerk, en of Discogs vandaag hetzelfde antwoordt als gisteren. Met de cache
erbij maakt de browser NUL aanroepen, en dan meet je nog maar een ding - of
match.py in Pyodide dezelfde persing kiest.

Geen hoesfoto's
---------------
`herken` laat de hoes het laatste woord hebben, en dat vraagt de uitsnede naast
de afbeelding op Discogs. Die beeldronde staat hier UIT, aan beide kanten, door
een lege hoezenmap mee te geven. Niet omdat hij er niet toe doet - hij ving vijf
foute persingen af - maar omdat je een verschil niet kunt toeschrijven als je
twee dingen tegelijk verandert. De beeldronde is een aparte meting.
"""
import os, sys, json, argparse

HIER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HIER)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("aantal", nargs="?", type=int, default=20)
    a = ap.parse_args()
    os.chdir(HIER)

    import match
    from discogs import Discogs

    groepen = json.load(open("uit/groepen.json", encoding="utf-8"))
    platen = json.load(open("uit/platen.json", encoding="utf-8"))
    verwacht_uit_run = {str(p["id"]): p.get("release_id_auto") for p in platen}

    # Gespreid kiezen, niet de eerste twintig: die komen uit een handvol
    # fotosessies achter elkaar en lijken te veel op elkaar. Een stap door de
    # hele set geeft singles, LP's, herkende en onherkende door elkaar.
    stap = max(1, len(groepen) // a.aantal)
    keuze = groepen[::stap][:a.aantal]

    dc = Discogs(os.environ.get("DISCOGS_TOKEN"))
    gebruikt = {}

    # Meeluisteren op de cache in plaats van hem achteraf uitpluizen: elke
    # sleutel die langskomt gaat mee, of hij nu uit de cache kwam of vers
    # opgehaald werd.
    echt_lees, echt_schrijf = dc._lees, dc._schrijf

    def lees(sleutel):
        w = echt_lees(sleutel)
        if w is not None:
            gebruikt[sleutel] = w
        return w

    def schrijf(sleutel, waarde):
        gebruikt[sleutel] = waarde
        return echt_schrijf(sleutel, waarde)

    dc._lees, dc._schrijf = lees, schrijf

    leeg = os.path.join(HIER, "uit", "_geen_hoezen")
    os.makedirs(leeg, exist_ok=True)

    uit = []
    for i, rec in enumerate(keuze, 1):
        rid, reden = None, None
        try:
            plaat, reden = match.herken(dc, rec, leeg)
            rid = plaat.get("release_id_auto") if plaat else None
        except Exception as e:
            reden = f"fout: {type(e).__name__}: {e}"
        uit.append({"id": rec["id"], "release": rid, "reden": reden,
                    "in_run": verwacht_uit_run.get(str(rec["id"]))})
        print(f"  {i:3}/{len(keuze)}  {str(rec['id'])[:26]:28} "
              f"{str(rid or '-'):10} {(reden or '')[:44]}", flush=True)

    doel = os.path.join(HIER, "site", "motor", "ijk", "match.json")
    os.makedirs(os.path.dirname(doel), exist_ok=True)
    with open(doel, "w", encoding="utf-8") as fh:
        json.dump({"records": keuze, "verwacht": uit, "cache": gebruikt},
                  fh, ensure_ascii=False)

    gevonden = sum(1 for u in uit if u["release"])
    gelijk = sum(1 for u in uit if str(u["release"]) == str(u["in_run"]))
    print(f"\n{gevonden} van de {len(uit)} herkend zonder beeldronde")
    print(f"{gelijk} gelijk aan de volle run (verschil = de beeldronde, die "
          f"hier uit staat)")
    print(f"{len(gebruikt)} Discogs-sleutels meegegeven, "
          f"{os.path.getsize(doel) / 1e6:.1f} MB -> site/motor/ijk/match.json")


if __name__ == "__main__":
    main()
