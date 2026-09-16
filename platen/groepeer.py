#!/usr/bin/env python3
"""
groepeer.py - groepeert de foto's per plaat, en vult de velden uit de tekst.
Vervangt het groepeerdeel van prep.py.

Waarom anders dan prep.py
-------------------------
prep.py begon een nieuwe plaat zodra een soort (voor/achter) terugkwam. Dat
etiket kwam uit de hoeveelheid tesseract-tekst, en die is onbruikbaar: 27% van
de foto's gaf nul tekens, en binnen strikte paren had de voorkant even vaak
MEER tekst dan de achterkant als minder (58 tegen 47). Elke fout gaf meteen een
extra plaat, vandaar 134 in plaats van ~110.

Gemeten op de 24 door Discogs geverifieerde platen (echte grondwaarheid):
  - alle 24 liggen aaneengesloten in de opnamevolgorde
  - 20 bestaan uit 2 foto's, 4 uit 3
  - de voorkant komt eerst, de achterkant als laatste (22 van de 24)
  - tijdgaten binnen een plaat: mediaan 7s, maar p90 al 22s, en tussen platen
    is de mediaan 13s. Die overlappen te veel om alleen daarop te knippen.

Daarom groeperen we op GEDEELDE TEKST in plaats van op de hoeveelheid ervan,
en knippen we de hele reeks in één keer optimaal op met dynamisch programmeren.
Zie groepsignaal.py voor de gemeten signalen en drempels.

Gemeten resultaat: 110 groepen, waarvan 21 van de 24 geverifieerde platen
exact gereproduceerd. prep.py maakte er 134.

    py groepeer.py --cache ocr2_cache.json --uit ruw2.json
"""
import os, re, sys, json, argparse, collections

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prep import uit_tekst, schrijf_kit
from groepsignaal import bouw_rijen, segmenteer

KOPRUIS = re.compile(r"(?i)^(stereo|mono|long play|lp|ep|33|45|rpm|side|kant|face|"
                     r"records?|hi.?fi|digital|remaster\w*)\W*$")


def koptekst(rijen, aantal=6):
    """De grootst gedrukte regels van de voorkant.

    Op een hoes staan artiest en titel in de grootste letters; de rest is
    klein. RapidOCR geeft per tekstvak de hoogte terug, dus die volgorde is
    gratis te krijgen. Dat is een veel betere zoekterm dan 'de langste regel',
    want de langste regel op een hoes is meestal een adres of een copyright.
    """
    vakken = []
    for r in rijen:
        for v in (r["c"].get("vakken") or []):
            t = " ".join((v.get("t") or "").split())
            if len(re.sub(r"[^A-Za-z]", "", t)) < 3 or len(t) > 60:
                continue
            if KOPRUIS.match(t):
                continue
            vakken.append((float(v.get("h") or 0), t))
    vakken.sort(key=lambda x: -x[0])
    uit, gezien = [], set()
    for _, t in vakken:
        k = re.sub(r"[^a-z0-9]", "", t.lower())
        if k and k not in gezien:
            gezien.add(k)
            uit.append(t)
        if len(uit) >= aantal:
            break
    return uit


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--indir", default="bijgeknipt")
    ap.add_argument("--cache", default="ocr2_cache.json")
    ap.add_argument("--kitdir", default="kit")
    ap.add_argument("--uit", default="ruw2.json")
    ap.add_argument("--geen-kit", action="store_true", dest="geen_kit")
    a = ap.parse_args()

    os.makedirs(a.kitdir, exist_ok=True)
    rijen = bouw_rijen(a.indir, a.cache)
    groepen = segmenteer(rijen)
    maten = dict(sorted(collections.Counter(len(g) for g in groepen).items()))
    print(f"{len(rijen)} foto's -> {len(groepen)} platen, groottes {maten}")

    uit, kosten = [], 0
    for g in groepen:
        fs = [rijen[i] for i in g]
        stam = re.sub(r"\D", "", fs[0]["naam"])[-6:] or fs[0]["naam"][:6]
        # Miro fotografeert altijd in dezelfde volgorde: eerst de voorkant, dan
        # de achterkant, en wat daarna komt is de binnenkant. De plaats in de
        # reeks is dus betrouwbaarder dan de hoeveelheid tekst, en juist op de
        # moeilijke hoezen (donker, weinig OCR) is dat het verschil: daar zegt
        # de hoeveelheid tekst niets meer en de volgorde nog alles.
        voor = [fs[0]]
        achter = [fs[1]] if len(fs) > 1 else [fs[0]]
        binnen = fs[2:]

        # de binnenkant telt mee als "achterkant": daar staat vaak de tracklist
        tekst_achter = "\n".join(r["c"].get("t") or "" for r in achter + binnen).strip()
        tekst_voor = "\n".join(r["c"].get("t") or "" for r in voor).strip()
        hoektekst = "\n".join(r["c"].get("h") or "" for r in fs).strip()

        velden = uit_tekst(tekst_achter + "\n" + tekst_voor + "\n" + hoektekst)
        hoek_kand = uit_tekst(hoektekst)["catno_kandidaten"]
        velden["catno_kandidaten"] = hoek_kand + [c for c in velden["catno_kandidaten"]
                                                  if c not in hoek_kand]

        beelden = {}
        if not a.geen_kit:
            for r in voor[:1]:
                beelden.update(schrijf_kit(r["pad"], a.kitdir, stam, "front"))
            for r in achter[:1]:
                beelden.update(schrijf_kit(r["pad"], a.kitdir, stam, "back"))
            kosten += sum(b["tokens"] for b in beelden.values())

        goed = (len(re.sub(r"\s", "", tekst_achter)) >= 350
                and bool(velden["catno_kandidaten"]) and bool(velden["land"]))
        uit.append({
            "id": stam,
            "fotos": [r["naam"] for r in fs],
            "ocr_kwaliteit": "goed" if goed else "zwak",
            "ocr_achterkant": tekst_achter[:4000],
            "ocr_voorkant": tekst_voor[:800],
            "ocr_hoekstrook": hoektekst[:800],
            "koptekst": koptekst(voor or fs),
            **velden,
            "beelden": beelden,
            "ocr_bron": "rapidocr",
        })

    json.dump(uit, open(a.uit, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    g = sum(1 for r in uit if r["ocr_kwaliteit"] == "goed")
    maten = {}
    for r in uit:
        maten[len(r["fotos"])] = maten.get(len(r["fotos"]), 0) + 1
    print(f"groepsgroottes: {dict(sorted(maten.items()))}")
    print(f"{g} met bruikbare OCR, {len(uit)-g} zwak")
    print(f"met catalogusnummer: {sum(1 for r in uit if r['catno_kandidaten'])}")
    print(f"-> {a.uit}")


if __name__ == "__main__":
    main()
