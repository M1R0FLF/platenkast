#!/usr/bin/env python3
"""
beeldmatch.py - herkent de overgebleven platen aan de HOES in plaats van aan
de tekst.

Waarom
------
Wat na automatch.py overblijft zijn hoezen waar de OCR te weinig van maakt om
een tracklist tegen te verifieren. Maar de hoes is een plaatje, en Discogs
heeft datzelfde plaatje. Gemeten op tien platen waarvan de persing al
vaststond:

    juiste hoes    : 76 tot 553 passende punten, mediaan 390
    verkeerde hoes : 0 tot 6

Dat is geen grijs gebied maar een kloof. Een drempel van 30 zit er ruim
tussenin. Een hoes die op vierhonderd punten meetkundig samenvalt is hardere
verificatie dan een tracklist, niet zachtere.

Wat het niet kan: zonder tekst is er geen zoekopdracht, en dus geen kandidaat
om de foto mee te vergelijken. Platen waar de OCR helemaal niets vond blijven
daarom liggen.

    py beeldmatch.py
    py beeldmatch.py --drempel 30 --max 5
"""
import os, re, sys, json, argparse, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cv2
from lookup import Discogs
from automatch import (kaal, zoektermen, tracktermen, catno_varianten,
                       soort_uit, onwaarschijnlijk, woordtermen)
from beeldgelijk import haal, kenmerken, gelijkenis


def kandidaten(dc, rec, hint=None):
    """Zo breed mogelijk zoeken.

    Bij automatch moest de zoekterm raak zijn, want daar besliste de tekst.
    Hier beslist de hoes, en die is keihard: de juiste haalde 76 tot 553
    passende punten, de verkeerde hoogstens 6. Dan is het beter om veel ruwe
    kandidaten te bekijken dan om een precieze zoekterm te willen hebben.

    Dat helpt juist waar de OCR woorden aan elkaar plakt. "WHYDOFOOLSFALLIN
    LOVE" levert niets op, maar het losse woord "ROSS" van de voorkant geeft
    een lijst waar de juiste plaat tussen staat, en het beeld wijst hem aan.
    """
    uit, gezien = [], set()

    def erbij(res, hoe):
        for r in res:
            if r["id"] not in gezien:
                gezien.add(r["id"])
                uit.append((hoe, r))

    # Een aangereikte artiest of titel verbreedt alleen de ZOEKOPDRACHT. Wat
    # er in platen.json belandt moet nog steeds door de hoesvergelijking heen,
    # en die vraagt dertig samenvallende punten waar een verkeerde hoes er
    # hoogstens zes haalt. Een verkeerde gok levert dus geen plaat op.
    if hint:
        kw = {"format": "Vinyl"}
        if hint.get("artist"):
            kw["artist"] = hint["artist"]
        if hint.get("title"):
            kw["release_title"] = hint["title"]
        if len(kw) > 1:
            erbij(dc.search(type="release", **kw)[:10], "hint artiest+titel")
        if hint.get("catno"):
            erbij(dc.search(type="release", catno=hint["catno"], format="Vinyl")[:8],
                  f"hint catno {hint['catno']}")
        q = " ".join(x for x in (hint.get("artist"), hint.get("title")) if x)
        if q:
            erbij(dc.search(type="release", q=q, format="Vinyl")[:10], f"hint {q}")

    for cat in (rec.get("catno_kandidaten") or [])[:4]:
        for v in catno_varianten(cat)[:2]:
            erbij(dc.search(type="release", catno=v, format="Vinyl")[:6], f"catno {v}")
    for q in zoektermen(rec)[:3]:
        erbij(dc.search(type="release", q=q, format="Vinyl")[:8], f"zoek {q}")

    # Losse schone woorden, los en in paren. Dit is wat het bij geplakte OCR
    # wel doet: "ROSS WHY" zet de juiste plaat op plek een waar de volledige
    # geplakte titel niets oplevert.
    woorden = woordtermen(rec)
    vragen = [" ".join(p) for p in
              [(woorden[i], woorden[j]) for i in range(len(woorden))
               for j in range(i + 1, min(i + 3, len(woorden)))]][:4]
    vragen += woorden[:2]
    for q in vragen:
        erbij(dc.search(type="release", q=q, format="Vinyl")[:12], f"woorden {q}")
        if len(uit) >= 40:
            break
    if len(uit) < 8:
        for t in tracktermen(rec)[:2]:
            erbij(dc.search(type="release", track=t, format="Vinyl")[:6], f"track {t}")
    return uit


def alle_beelden(dc, rid):
    """Alle afbeeldingen van een release, niet alleen de voorkant.

    Van sommige platen bestaat maar één foto, en dat is soms de ACHTERkant.
    Die valt nooit samen met het omslagplaatje, maar Discogs bewaart de
    achterkant er meestal bij.
    """
    rel = dc.release(rid)
    if not rel:
        return [], None
    return [i.get("uri") for i in (rel.get("images") or [])[:4] if i.get("uri")], rel


def fotos_van(rec, indir):
    uit = []
    for naam in (rec.get("fotos") or []):
        im = cv2.imread(os.path.join(indir, naam))
        if im is not None:
            uit.append((naam, kenmerken(im)))
    return uit


def beoordeel(dc, rec, indir, drempel, marge, hint=None):
    eigen = fotos_van(rec, indir)
    if not eigen:
        return None, "geen leesbare foto"
    kand = kandidaten(dc, rec, hint)
    if not kand:
        return None, "geen kandidaat op Discogs (te weinig tekst om te zoeken)"

    def straf_van(r):
        return onwaarschijnlijk(
            r.get("country"),
            r.get("label") if isinstance(r.get("label"), list) else [])

    # Ronde 1: alleen de omslagfoto uit het zoekresultaat. Geen extra aanroep.
    scores = []
    for hoe, r in kand[:30]:
        hoes = haal(r.get("cover_image") or r.get("thumb"))
        if hoes is None:
            continue
        kh = kenmerken(hoes)
        best = max((gelijkenis(kf, kh)[1] for _, kf in eigen), default=0)
        scores.append((best - 3 * straf_van(r), best, hoe, r))

    if not scores:
        return None, "geen hoesafbeeldingen gevonden"
    scores.sort(key=lambda s: -s[0])

    # Ronde 2: niets gevonden? Dan is onze foto misschien de achterkant. Haal
    # van de beste kandidaten alle afbeeldingen op en vergelijk daar ook mee.
    if scores[0][1] < drempel:
        for _, _, hoe, r in scores[:4]:
            uris, _rel = alle_beelden(dc, r["id"])
            for u in uris[1:]:
                hoes = haal(u)
                if hoes is None:
                    continue
                kh = kenmerken(hoes)
                best = max((gelijkenis(kf, kh)[1] for _, kf in eigen), default=0)
                if best >= drempel:
                    scores.append((best - 3 * straf_van(r), best,
                                   hoe + " (achterkant)", r))
        scores.sort(key=lambda s: -s[0])

    top = scores[0]
    if top[1] < drempel:
        return None, f"beeld komt niet overeen (beste {top[1]} punten)"

    rel = dc.release(top[3]["id"])
    if not rel:
        return None, "release niet op te halen"
    titels = [t["title"] for t in (rel.get("tracklist") or []) if t.get("title")]
    labels = rel.get("labels") or [{}]
    return {
        "id": rec["id"],
        "fotos": rec.get("fotos") or [],
        "artist": ", ".join(a["name"] for a in (rel.get("artists") or []))[:120] or None,
        "title": rel.get("title"),
        "label": labels[0].get("name"),
        "catno": labels[0].get("catno"),
        "barcode": rec.get("barcode"),
        "country": rel.get("country"),
        "year": rel.get("year") or rec.get("jaar"),
        "soort": soort_uit(rel, len(titels)),
        "lp_count": int((rel.get("formats") or [{}])[0].get("qty") or 1),
        "gatefold": "gatefold" in " ".join(
            (f.get("text") or "") + " ".join(f.get("descriptions") or [])
            for f in (rel.get("formats") or [])).lower(),
        "a_kant": None, "b_kant": None,
        "aantal_nummers": len(titels),
        "notes": f"herkend aan de hoes: {top[1]} passende punten met de "
                 f"afbeelding op Discogs (gevonden via {top[2]})",
        "staat_hoes": None,
        "bron": "beeld",
        "release_id_auto": rel["id"],
    }, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("invoer", nargs="?", default="voor_claude.json")
    ap.add_argument("uitvoer", nargs="?", default="platen.json")
    ap.add_argument("--rest", default="voor_claude.json")
    ap.add_argument("--indir", default="bijgeknipt")
    ap.add_argument("--drempel", type=int, default=30)
    ap.add_argument("--marge", type=float, default=1.6)
    ap.add_argument("--max", type=int, default=0)
    ap.add_argument("--hints", default=None,
                    help="JSON-lijst met id/artist/title/catno, alleen om "
                         "breder mee te zoeken; de hoes blijft beslissen")
    a = ap.parse_args()

    rest = json.load(open(a.invoer, encoding="utf-8"))
    if a.max:
        rest = rest[:a.max]
    klaar = json.load(open(a.uitvoer, encoding="utf-8")) if os.path.exists(a.uitvoer) else []
    hebben = {str(r["id"]) for r in klaar}

    hints = {}
    if a.hints and os.path.exists(a.hints):
        hints = {str(h["id"]): h for h in json.load(open(a.hints, encoding="utf-8"))}
        print(f"{len(hints)} zoekhints geladen uit {a.hints}")

    dc = Discogs(os.environ.get("DISCOGS_TOKEN"))
    gelukt, over = 0, []
    t0 = time.time()
    for i, rec in enumerate(rest, 1):
        if str(rec["id"]) in hebben:
            continue
        res, reden = beoordeel(dc, rec, a.indir, a.drempel, a.marge,
                               hints.get(str(rec["id"])))
        if res:
            klaar.append(res)
            gelukt += 1
            json.dump(klaar, open(a.uitvoer, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
            print(f"[{i}/{len(rest)}] {rec['id']}  HOES  {res['artist']} - {res['title']} "
                  f"({res['country']} {res['year']})", flush=True)
        else:
            over.append(rec)
            print(f"[{i}/{len(rest)}] {rec['id']}  nee   {reden}", flush=True)
        dc.bewaar()

    dc.bewaar(True)
    json.dump(klaar, open(a.uitvoer, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(over, open(a.rest, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n{gelukt} erbij via de hoes in {int(time.time()-t0)}s, "
          f"{len(klaar)} in {a.uitvoer}, {len(over)} blijven over")


if __name__ == "__main__":
    main()
