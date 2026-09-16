#!/usr/bin/env python3
"""
stand.py - zet de uitsnedes rechtop, met de hoes op Discogs als grondwaarheid.

Waarom dit apart staat, en waarom het na het herkennen komt
-----------------------------------------------------------
knip.rechtop moet raden. Het draait voordat er ook maar iets van de plaat
bekend is, dus het heeft alleen de foto zelf: de VORM van de tekstvakken zegt
of de tekst op zijn kant staat, en het hoekmodel van RapidOCR zegt 0 of 180.
Dat werkt op een achterkant vol tekst en het werkt niet op een fotohoes met
drie woorden erop. Gemeten over 90 voorkanten stond 22 procent verkeerd:
acht een kwartslag, negen ondersteboven, drie andersom een kwartslag.

Zodra de persing bekend is, hoeft er niets meer geraden te worden. De hoes
staat op Discogs, ORB is rotatie-invariant, en de homografie tussen onze
uitsnede en die hoes BEVAT de draaiing. Dat is geen aanwijzing maar een
meting, en ze komt er schoon uit: 0,2 - 90,5 - 179,7 graden, nooit iets
ertussenin.

Dit draait dus na run.py en voor exporteer.py, en het is idempotent: wat
eenmaal rechtstaat meet daarna nul en wordt niet nog eens gedraaid.

    py stand.py              meten en rechtzetten
    py stand.py --proef      alleen meten, niets aanraken
"""
import os, sys, json, math, argparse
import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import beeld
from discogs import Discogs
from beeldtoets import cover_urls

# Onder dit aantal samenvallende punten zegt de homografie niets. De gemeten
# juiste hoezen zaten op 62 tot 749 punten; 25 ligt daar ruim onder en nog
# altijd ruim boven de 5 a 6 van een toevallige match.
DREMPEL = 25

# Hoeveel graden een uitsnede van een kwartslag af mag liggen. De perspectief-
# correctie in knip.snijd is goed, dus dit blijft in de praktijk onder de 2
# graden; iets dat er 20 naast zit is geen scheve foto maar een slechte meting.
SPELING = 12.0

KWALITEIT = 92          # zelfde als foto.py, zodat herdraaien niets kost


def _hoek(kf, kh):
    """(graden, inliers) van onze uitsnede naar de hoes op Discogs.

    Dit is beeld.gelijkenis, maar dan met de homografie zelf in plaats van
    alleen het aantal punten dat hem overleefde.
    """
    kpA, desA = kf
    kpB, desB = kh
    if desA is None or desB is None or len(desA) < 10 or len(desB) < 10:
        return None, 0
    bf = cv2.BFMatcher(cv2.NORM_HAMMING)
    try:
        paren = bf.knnMatch(desA, desB, k=2)
    except cv2.error:
        return None, 0
    goed = [m for m, n in (p for p in paren if len(p) == 2)
            if m.distance < 0.75 * n.distance]
    if len(goed) < 8:
        return None, 0
    src = np.float32([kpA[m.queryIdx].pt for m in goed]).reshape(-1, 1, 2)
    dst = np.float32([kpB[m.trainIdx].pt for m in goed]).reshape(-1, 1, 2)
    try:
        H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
    except cv2.error:
        return None, 0
    if H is None or mask is None:
        return None, 0
    n = int(mask.sum())
    # waar wijst een horizontale eenheidsvector heen na de transformatie
    p = cv2.perspectiveTransform(np.float32([[[0, 0]], [[100, 0]]]), H).reshape(2, 2)
    v = p[1] - p[0]
    return math.degrees(math.atan2(v[1], v[0])) % 360, n


def meet(pad, refs):
    """(kwartslagen, graden, punten) voor een uitsnede, of (None, None, n).

    kwartslagen is hoe vaak deze foto met de klok mee moet om rechtop te staan.
    """
    im = cv2.imread(pad)
    if im is None:
        return None, None, 0
    kf = beeld.kenmerken(im)
    if kf[1] is None:
        return None, None, 0
    beste = (None, 0)
    for kh in refs:
        g, n = _hoek(kf, kh)
        if g is not None and n > beste[1]:
            beste = (g, n)
    g, n = beste
    if g is None or n < DREMPEL:
        return None, g, n
    k = int(round(g / 90.0)) % 4
    if abs((g - k * 90 + 180) % 360 - 180) > SPELING:
        return None, g, n            # geen nette kwartslag; niet aankomen
    return k, g, n


# Met de klok mee, en dat is gemeten en niet beredeneerd. De homografie loopt
# van onze uitsnede naar de hoes op Discogs, dus of de hoek het beeld of het
# assenstelsel beschrijft is precies het soort teken waar je een uur aan kwijt
# bent. Drie platen, alle drie de draairichtingen geprobeerd, opnieuw gemeten:
#   ABBA 170039   gemeten 90,5  -> met de klok mee 0,5   tegen de klok in 180,0
#   Gouden Uren   gemeten 179,7 -> 180 geeft 0,06
#   Croisille     gemeten 91,1  -> met de klok mee 359,6
DRAAI = {1: cv2.ROTATE_90_CLOCKWISE,
         2: cv2.ROTATE_180,
         3: cv2.ROTATE_90_COUNTERCLOCKWISE}


def zet_recht(pad, kwartslagen):
    im = cv2.imread(pad)
    if im is None or kwartslagen not in DRAAI:
        return False
    cv2.imwrite(pad, cv2.rotate(im, DRAAI[kwartslagen]),
                [cv2.IMWRITE_JPEG_QUALITY, KWALITEIT])
    return True


def refs_van(dc, release_id, maxaantal=3):
    urls, _ = cover_urls(dc, release_id)
    uit = []
    for u in urls[:maxaantal]:
        im = beeld.haal(u)
        if im is None:
            continue
        k = beeld.kenmerken(im)
        if k[1] is not None:
            uit.append(k)
    return uit


def loop(platen, hoezendir, dc, proef=False, melden=None):
    zeg = melden or (lambda *a, **k: None)
    uitslag = []
    for i, p in enumerate(platen, 1):
        rid = p.get("release_id_auto")
        fotos = p.get("fotos") or []
        refs = refs_van(dc, rid) if rid else []
        voor_k = None
        for slot, naam in enumerate(fotos, 1):
            pad = os.path.join(hoezendir, os.path.basename(naam))
            k, g, n = (None, None, 0) if not refs else meet(pad, refs)
            if slot == 1:
                voor_k = k
            gedraaid = False
            if k:
                gedraaid = proef or zet_recht(pad, k)
            uitslag.append({"id": p["id"], "slot": slot, "foto": naam,
                            "kwartslagen": k, "graden": None if g is None else round(g, 1),
                            "punten": n, "gedraaid": bool(k) and gedraaid,
                            "voorkant_kwartslagen": voor_k})
            zeg(p["id"], slot, k, g, n)
        if i % 10 == 0:
            zeg("voortgang", i, len(platen), None, None)
    return uitslag


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--platen", default="uit/platen.json")
    ap.add_argument("--hoezen", default="hoezen")
    ap.add_argument("--uit", default="uit/stand.json")
    ap.add_argument("--proef", action="store_true", help="alleen meten")
    a = ap.parse_args()

    platen = json.load(open(a.platen, encoding="utf-8"))
    dc = Discogs(os.environ.get("DISCOGS_TOKEN"))

    def zeg(pid, slot, k, g, n):
        if pid == "voortgang":
            print(f"    ... {slot}/{k if k else ''}", flush=True)
            return
        merk = "" if not k else f"  <<< {k * 90} graden gedraaid"
        print(f"  {pid}-{slot}  {str(g) if g is not None else '-':>6} gr  "
              f"{n:>4} pt{merk}", flush=True)

    uitslag = loop(platen, a.hoezen, dc, a.proef, zeg)
    json.dump(uitslag, open(a.uit, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    gemeten = [u for u in uitslag if u["kwartslagen"] is not None]
    gedraaid = [u for u in gemeten if u["kwartslagen"]]
    print("\n" + "=" * 66)
    print(f"  foto's              {len(uitslag)}")
    print(f"  gemeten             {len(gemeten)}")
    print(f"  stonden goed        {len(gemeten) - len(gedraaid)}")
    print(f"  {'zou draaien' if a.proef else 'rechtgezet':<19} {len(gedraaid)}")
    for k in (1, 2, 3):
        n = sum(1 for u in gedraaid if u["kwartslagen"] == k)
        if n:
            print(f"     {k * 90:>3} graden: {n}")
    print(f"  niet te meten       {len(uitslag) - len(gemeten)}")

    # Klopt de aanname dat de achterkant net zo op tafel lag als de voorkant?
    # Alleen te beantwoorden waar allebei gemeten zijn.
    paar = [u for u in uitslag if u["slot"] > 1 and u["kwartslagen"] is not None
            and u["voorkant_kwartslagen"] is not None]
    if paar:
        gelijk = sum(1 for u in paar if u["kwartslagen"] == u["voorkant_kwartslagen"])
        print(f"\n  achterkant net zo gedraaid als de voorkant: "
              f"{gelijk} van {len(paar)}")
    print(f"\n-> {a.uit}")


if __name__ == "__main__":
    main()
