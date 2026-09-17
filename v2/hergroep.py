#!/usr/bin/env python3
"""
hergroep.py - laat het BEELD zeggen waar de ene plaat ophoudt en de volgende
begint.

Het probleem
------------
groep.segmenteer weegt tekst: een gedeeld catalogusnummer, overlappende
trigrammen, het tijdgat. Op een hoes vol drukwerk is dat genoeg. Op een reeks
fotohoezen achter elkaar is er geen tekst, zijn alle bindingen even zwak, en
wint PRIOR - die een paar beloont. Dan wordt elke reeks keurig in paren
geknipt, ongeacht waar de platen echt beginnen.

Precies dat gebeurde hier. Zeven foto's:

    161046 Vinton voor | 161056 Vinton achter | 161115 Vinton BINNENWERK
    161133 Met Liefde voor | 161142 Met Liefde achter
    161156 'n Vriend voor | 161203 'n Vriend achter

werden 2 + 2 + 3 in plaats van 3 + 2 + 2. Elke grens schoof een foto op, dus
het binnenwerk van Vinton kwam bij Hazes terecht, Met Liefde kreeg twee
platen, en 'n Vriend kreeg er nul - dat album zat wel in de kast en niet in
de catalogus.

De oplossing
------------
Na het herkennen staat van elke plaat de hoes op Discogs. Elke foto wordt
tegen al die hoezen gelegd; ORB is rotatie-invariant en Discogs heeft ook de
binnenkant van een gatefold, dus 161115 matcht Vinton op 129 punten. Twee
foto's naast elkaar die AANTOONBAAR bij dezelfde persing horen mogen niet
uit elkaar geknipt worden, en twee die aantoonbaar bij verschillende horen
moeten juist wel.

Dat is bewijs van een andere soort dan de tekst, en het is er gratis.

    py hergroep.py          labels bepalen en wegschrijven
"""
import os, sys, json, argparse
import cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import beeld
from discogs import Discogs
from beeldtoets import cover_urls
from groep import MAXGROOTTE, stempel

# Ruim boven de 5 a 6 punten van een toevallige match en ruim onder de 76 die
# de zwakste ECHTE match haalde. Zie beeld.py.
DREMPEL = 40

# Hoeveel seconden er hoogstens tussen twee foto's van dezelfde plaat zit.
# Alleen als extra rem op "samen": twee losse exemplaren van dezelfde persing
# leveren hetzelfde label op, en die horen niet aan elkaar geplakt te worden.
MAXGAT = 30


def labels(platen, hoezendir, dc, melden=None):
    """{fotonaam: release_id} voor elke foto die aantoonbaar een hoes toont."""
    zeg = melden or (lambda *a, **k: None)
    ref = {}
    for p in platen:
        rid = p.get("release_id_auto")
        if not rid or rid in ref:
            continue
        ks = []
        # Ruim kijken: binnenwerk van een gatefold staat verderop in de rij
        # afbeeldingen, en juist die foto's zijn met tekst niet te plaatsen.
        for u in cover_urls(dc, rid, maxaantal=10)[0][:8]:
            im = beeld.haal(u)
            if im is not None:
                k = beeld.kenmerken(im)
                if k[1] is not None:
                    ks.append(k)
        if ks:
            ref[rid] = ks
    zeg("refs", len(ref))

    uit = {}
    fotos = [(naam, p) for p in platen for naam in (p.get("fotos") or [])]
    for i, (naam, p) in enumerate(fotos, 1):
        im = cv2.imread(os.path.join(hoezendir, os.path.basename(naam)))
        if im is None:
            continue
        kf = beeld.kenmerken(im)
        if kf[1] is None:
            continue
        beste, bn = None, 0
        for rid, ks in ref.items():
            n = max((beeld.gelijkenis(kf, kh) for kh in ks), default=0)
            if n > bn:
                beste, bn = rid, n
        if beste is not None and bn >= DREMPEL:
            uit[os.path.splitext(os.path.basename(naam))[0]] = {
                "release": beste, "punten": bn}
        zeg("foto", i, len(fotos), naam, beste if bn >= DREMPEL else None, bn)
    return uit


def eisen(fotonamen, lab):
    """Van labels naar harde grenzen: {fotonaam: "knip"|"samen"}.

    fotonamen staat op opnamevolgorde, want alleen buren kunnen elkaar iets
    vertellen over een grens.
    """
    uit = {}
    for i in range(1, len(fotonamen)):
        a, b = lab.get(fotonamen[i - 1]), lab.get(fotonamen[i])
        if not a or not b:
            continue
        if a["release"] != b["release"]:
            uit[fotonamen[i]] = "knip"
            continue
        ta, tb = stempel(fotonamen[i - 1]), stempel(fotonamen[i])
        if ta and tb and (tb - ta).total_seconds() > MAXGAT:
            continue          # zelfde persing, maar een los tweede exemplaar
        uit[fotonamen[i]] = "samen"

    # Een foto die met geen enkele hoes matcht is bijna altijd een achterkant
    # of binnenwerk. Daar begint zelden een plaat, dus liever niet knippen -
    # maar het blijft een voorkeur, want van sommige persingen heeft Discogs
    # geen bruikbare afbeelding en dan is de voorkant net zo goed labelloos.
    for i in range(1, len(fotonamen)):
        if fotonamen[i] not in lab and fotonamen[i] not in uit:
            uit[fotonamen[i]] = "liever_samen"

    # Een reeks die langer wordt dan een plaat mag zijn is geen plaat maar
    # twee exemplaren van dezelfde persing. Dan liever niets eisen dan iets
    # onmogelijks: de gewone afweging doet het beter dan een kapotte eis.
    i = 0
    while i < len(fotonamen):
        j = i + 1
        while j < len(fotonamen) and uit.get(fotonamen[j]) == "samen":
            j += 1
        if j - i > MAXGROOTTE:
            for k in range(i + 1, j):
                uit.pop(fotonamen[k], None)
        i = j
    return uit



def hints_van(groepenpad, lab, hintpad="hints.json", minstens=80):
    """Vult hints.json aan met de persing die het beeld aanwijst.

    match.herken slaat het zoeken over zodra er een release in de hint staat,
    en meet alleen nog na of de hoes klopt. Dat scheelt niet alleen tijd maar
    redt ook platen die met tekst niet te vinden ZIJN: "Gouden Uren" staat in
    sierletters op de hoes, de OCR maakt er "louden Vten" van, en daar valt
    niets mee te zoeken. Het beeld wist het allang - 259 punten.

    Met de hand gezette hints blijven staan; hier komt alleen een release bij.
    De drempel ligt hoger dan bij het groeperen: een grens verkeerd zetten
    kost een herknip, een persing verkeerd zetten kost een verkeerde prijs.
    """
    import json as _json
    groepen = _json.load(open(groepenpad, encoding="utf-8"))
    oud = []
    if os.path.exists(hintpad):
        try:
            oud = _json.load(open(hintpad, encoding="utf-8"))
        except (OSError, ValueError):
            oud = []
    per_id = {str(h["id"]): dict(h) for h in oud}

    bij = 0
    for g in groepen:
        stemmen = {}
        for f in (g.get("fotos") or []):
            l = lab.get(os.path.splitext(os.path.basename(f))[0])
            if l and l["punten"] >= minstens:
                stemmen[l["release"]] = max(stemmen.get(l["release"], 0), l["punten"])
        if not stemmen:
            continue
        # Bij onenigheid binnen een groep niets zeggen: dan staan er twee
        # platen in en is de groepering het probleem, niet de persing.
        if len(stemmen) > 1:
            continue
        rid, pt = next(iter(stemmen.items()))
        h = per_id.setdefault(str(g["id"]), {"id": str(g["id"])})
        if h.get("release") != rid:
            bij += 1
        h["release"] = rid
        h["bron"] = f"beeld: {pt} punten"
    uit = sorted(per_id.values(), key=lambda h: str(h["id"]))
    _json.dump(uit, open(hintpad, "w", encoding="utf-8"),
               ensure_ascii=False, indent=1)
    return len(uit), bij


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--platen", default="uit/platen.json")
    ap.add_argument("--hoezen", default="hoezen")
    ap.add_argument("--uit", default="uit/fotolabels.json")
    a = ap.parse_args()

    platen = json.load(open(a.platen, encoding="utf-8"))
    dc = Discogs(os.environ.get("DISCOGS_TOKEN"))

    def zeg(soort, *k):
        if soort == "refs":
            print(f"{k[0]} persingen met een vergelijkbare hoes\n", flush=True)
        else:
            i, n, naam, rid, pt = k
            print(f"[{i:>3}/{n}] {os.path.basename(naam):<28} "
                  f"{str(rid or '-'):>10}  {pt:>4} pt", flush=True)

    lab = labels(platen, a.hoezen, dc, zeg)
    namen = sorted({os.path.splitext(os.path.basename(f))[0]
                    for p in platen for f in (p.get("fotos") or [])},
                   key=lambda n: (stempel(n) or n, n))
    eis = eisen(namen, lab)

    json.dump({"labels": lab, "eisen": eis}, open(a.uit, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    tot, bij = hints_van(os.path.join(os.path.dirname(a.uit), "groepen.json"), lab)
    print(f"hints.json: {tot} hints, {bij} persingen uit het beeld toegevoegd")
    print("\n" + "=" * 60)
    print(f"  foto's met een aantoonbare hoes   {len(lab)} van {len(namen)}")
    print(f"  verplichte knippen                {sum(1 for v in eis.values() if v == 'knip')}")
    print(f"  verplicht samen                   {sum(1 for v in eis.values() if v == 'samen')}")
    print(f"\n-> {a.uit}")


if __name__ == "__main__":
    main()
