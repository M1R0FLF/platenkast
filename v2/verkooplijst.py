#!/usr/bin/env python3
"""
verkooplijst.py - de korte lijst om mee te werken.

platen.csv heeft veertig kolommen omdat alles wat de keten weet erin bewaard
blijft: waarop een plaat herkend is, welke alternatieven er waren, hoeveel
exemplaren er te koop staan. Dat is nodig om een keuze te kunnen nakijken, maar
niet om een advertentie te maken.

Deze lijst heeft alleen wat je nodig hebt als je gaat verkopen, gesorteerd op
artiest. Puntkomma's en een BOM, want zo opent Excel een CSV in Nederland
zonder dat alles in een kolom belandt.

    py verkooplijst.py
"""
import os, csv, json, argparse

KOLOMMEN = ["artiest", "titel", "soort", "jaar", "label", "catalogusnummer",
            "persing", "vraagprijs", "advies", "foto's", "discogs"]

# de keten gebruikt korte codes; op een verkooplijst lees je liever gewoon wat
# het is
SOORT = {"LP": "LP", "single7": "single", "maxi12": "maxi"}


def rij(r):
    # liever het veld van Discogs dan wat de OCR ervan maakte: dat is de
    # geverifieerde persing, met de juiste schrijfwijze en accenten
    def kies(*namen):
        for n in namen:
            v = (r.get(n) or "").strip()
            if v and v != "0":
                return v
        return ""

    return {
        "artiest": kies("artiest_discogs", "gelezen_artist"),
        "titel": kies("titel_discogs", "gelezen_title"),
        "soort": SOORT.get(kies("gelezen_soort"), kies("gelezen_soort")),
        "jaar": kies("jaar_discogs", "gelezen_year"),
        "label": kies("label_discogs", "gelezen_label"),
        "catalogusnummer": kies("catno_discogs", "gelezen_catno"),
        "persing": kies("land_discogs", "gelezen_country"),
        "vraagprijs": kies("vraagprijs"),
        "advies": kies("advies"),
        "foto's": kies("fotos"),
        "discogs": kies("discogs_url"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="bron", default="uit/platen.csv")
    ap.add_argument("--uit", default="uit/verkooplijst.csv")
    a = ap.parse_args()

    with open(a.bron, encoding="utf-8-sig", newline="") as fh:
        rijen = [rij(r) for r in csv.DictReader(fh)]
    rijen.sort(key=lambda r: (r["artiest"].lower(), r["titel"].lower()))

    os.makedirs(os.path.dirname(a.uit) or ".", exist_ok=True)
    with open(a.uit, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=KOLOMMEN, delimiter=";")
        w.writeheader()
        w.writerows(rijen)

    metprijs = sum(1 for r in rijen if r["vraagprijs"])
    totaal = sum(float(r["vraagprijs"]) for r in rijen if r["vraagprijs"])
    print(f"{a.uit}: {len(rijen)} platen, {metprijs} met vraagprijs, "
          f"samen {totaal:.0f} euro")

    rest = "uit/handmatig.json"
    if os.path.exists(rest):
        n = len(json.load(open(rest, encoding="utf-8")))
        if n:
            print(f"{n} niet herkend, die staan in {rest}")


if __name__ == "__main__":
    main()
