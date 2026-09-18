#!/usr/bin/env python3
"""
beeldtoets.py - klopt de HOES bij de persing die gekozen is?

Waarom dit apart staat
----------------------
De keten kent drie strategieen en het beeld is de derde: hij komt pas aan de
beurt als tekst niets oplevert. Een plaat die op tekst door de verificatie
komt, wordt dus nooit met zijn eigen hoesfoto vergeleken.

Dat gaat mis bij een achterkant die reclame maakt voor de rest van het fonds.
Op de ABBA-single "Under Attack" staat letterlijk "Extrait du double album 30cm
<<The Singles>> - 406506". Titel en catalogusnummer van een ANDERE plaat, netjes
bij elkaar, en dus precies waar strategie 2 (titel + catalogusnummer) op
afgaat. Het werd "The Singles - The First Ten Years", een dubbel-LP, terwijl er
een 7"-single in de hoes zit.

De hoes zelf spreekt dat meteen tegen, en meetbaar: juiste hoes 76 tot 766
samenvallende punten, verkeerde hoogstens 6. Dit script houdt die maatlat langs
alles wat al herkend is.

    py beeldtoets.py                 alles nakijken
    py beeldtoets.py --drempel 20
"""
import os, sys, json, argparse
import cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import beeld
from discogs import Discogs

# Uit beeld.py: onder de tien is het aantoonbaar een andere hoes, boven de
# dertig aantoonbaar dezelfde. Daartussen zegt de meting niets hards - meestal
# een donkere of spiegelende foto met te weinig structuur.
ZEKER_FOUT, ZEKER_GOED = 10, 30


def cover_urls(dc, release_id, maxaantal=4):
    """Alleen afbeeldingen die een HOES kunnen zijn.

    Zie match.kan_hoes_zijn: bij sommige persingen staan op Discogs alleen
    liggende foto's van het plaatje. Die meetellen maakt van "niets te
    vergelijken" ten onrechte "spreekt tegen".

    `maxaantal` staat laag omdat de eerste afbeelding vrijwel altijd de
    voorkant is en elke extra een aanroep kost. Wie binnenwerk wil herkennen
    moet hoger: op West Side Story staan 37 afbeeldingen en de binnenkant van
    de gatefold is de vierde. Met de standaardgrens bleven drie van de vier
    eigen foto's onherkend, en viel die plaat in tweeen uiteen.
    """
    from match import kan_hoes_zijn
    rel = dc.release(release_id) or {}
    uit = [i.get("uri") or i.get("resource_url")
           for i in (rel.get("images") or [])[:maxaantal] if kan_hoes_zijn(i)]
    return uit, rel


def toets(dc, rec, hoezendir):
    """(punten, oordeel, extra) voor een herkende plaat."""
    eigen = []
    for naam in (rec.get("fotos") or [])[:2]:      # voor- en achterkant
        im = cv2.imread(os.path.join(hoezendir, os.path.basename(naam)))
        if im is not None:
            eigen.append(beeld.kenmerken(im))
    if not eigen:
        return None, "geen foto", {}

    rid = rec.get("release_id_auto")
    if not rid:
        return None, "geen release", {}
    urls, rel = cover_urls(dc, rid)
    if not urls:
        return None, "geen hoesfoto op discogs", {}

    top = 0
    for u in urls:
        hoes = beeld.haal(u)
        if hoes is None:
            continue
        kh = beeld.kenmerken(hoes)
        top = max(top, max((beeld.gelijkenis(kf, kh) for kf in eigen), default=0))
        if top >= ZEKER_GOED:
            break
    extra = {"discogs_formaat": "; ".join(
        f"{f.get('qty')}x {f.get('name')} {' '.join(f.get('descriptions') or [])}".strip()
        for f in (rel.get("formats") or []))}
    oordeel = ("klopt" if top >= ZEKER_GOED
               else "SPREEKT TEGEN" if top < ZEKER_FOUT else "onduidelijk")
    return top, oordeel, extra


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--platen", default="uit/platen.json")
    ap.add_argument("--hoezen", default="hoezen")
    ap.add_argument("--uit", default="uit/beeldtoets.json")
    a = ap.parse_args()

    platen = json.load(open(a.platen, encoding="utf-8"))
    dc = Discogs(os.environ.get("DISCOGS_TOKEN"))

    uitslag, tel = [], {}
    for i, p in enumerate(platen, 1):
        punten, oordeel, extra = toets(dc, p, a.hoezen)
        tel[oordeel] = tel.get(oordeel, 0) + 1
        uitslag.append({"id": p["id"], "artist": p.get("artist"),
                        "title": p.get("title"), "bron": p.get("bron"),
                        "soort": p.get("soort"), "punten": punten,
                        "oordeel": oordeel, **extra})
        vlag = "  <<<" if oordeel == "SPREEKT TEGEN" else ""
        print(f"[{i:>3}/{len(platen)}] {p['id']}  {str(punten):>4} punten  "
              f"{oordeel:<14} {(p.get('artist') or '')[:24]:<26}"
              f"{(p.get('title') or '')[:30]}{vlag}", flush=True)

    json.dump(uitslag, open(a.uit, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    print("\n" + "=" * 66)
    for k in ("klopt", "onduidelijk", "SPREEKT TEGEN"):
        print(f"  {k:<16} {tel.get(k, 0)}")
    for k, v in tel.items():
        if k not in ("klopt", "onduidelijk", "SPREEKT TEGEN"):
            print(f"  {k:<16} {v}")

    fout = [u for u in uitslag if u["oordeel"] == "SPREEKT TEGEN"]
    if fout:
        print(f"\n{len(fout)} platen waarvan de hoes NIET bij de persing past:")
        for u in fout:
            print(f"  {u['id']}  {u['punten']:>3} punten  [{u['bron']}]  "
                  f"{(u['artist'] or '')[:26]} - {(u['title'] or '')[:34]}")
            print(f"        wij lazen {u['soort']}, discogs zegt {u.get('discogs_formaat')}")
    print(f"\n-> {a.uit}")


if __name__ == "__main__":
    main()
