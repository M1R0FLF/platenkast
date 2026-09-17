#!/usr/bin/env python3
"""
exporteer.py - van de keten naar de site.

De keten levert platen.csv (veertig kolommen), platen.json, groepen.json en een
map hoezen/ van 485 MB. Een website kan daar niets mee: 485 MB aan uitsnedes
downloadt niemand, en veertig kolommen zijn er achtendertig te veel om naar te
kijken.

Dit maakt er twee dingen van:

    site/publiek/collectie.json   alles wat de site toont, ~200 KB
    site/publiek/duim/*.jpg       dezelfde hoezen op 600 pixels, ~15 MB

Dat is een factor dertig kleiner en het is precies genoeg: een tegel in een
raster is nooit groter dan 300 pixels, en wie de foto op ware grootte wil heeft
hoezen/ gewoon op zijn eigen schijf staan.

    py exporteer.py
"""
import os, re, csv, json, hashlib, argparse
import cv2

DUIM = 600          # lange zijde; twee keer een tegel van 300 voor scherpe schermen
KWALITEIT = 82


def _getal(v):
    """CSV geeft alles als tekst terug, ook lege velden. Die moeten null worden
    en geen 0: een plaat zonder marktdata is iets anders dan een plaat die
    nul euro waard is."""
    if v is None:
        return None
    v = str(v).strip()
    if not v:
        return None
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return round(float(v), 2)
    except ValueError:
        return None


def _lijst(v, scheider=";"):
    return [x.strip() for x in (v or "").split(scheider) if x.strip()]


def _tracks(v):
    """De tracklist staat als 'A1 Titel | A2 Titel' in de CSV."""
    uit = []
    for deel in _lijst(v, "|"):
        m = re.match(r"^([AB]?\d{0,2})\s+(.*)$", deel)
        uit.append({"positie": m.group(1), "titel": m.group(2)} if m
                   else {"positie": "", "titel": deel})
    return uit


def _met_stempel(naam, pad):
    """De duimnagel met een inhoudsstempel achter de naam.

    De bestandsnaam van een duimnagel is altijd dezelfde (161816-1.jpg) maar de
    inhoud verandert bij elke herknip of draaiing. Een browser die hem eenmaal
    heeft bewaard vraagt er niet meer om, en dan kijk je naar de vorige versie
    terwijl de nieuwe allang live staat. Precies dat gebeurde: drie keer op rij
    zag Miro hoezen op hun kant staan die hier rechtop stonden.

    De cache-header aanpassen helpt daar niet tegen. Wat al in de cache ligt
    blijft daar liggen tot de OUDE max-age verlopen is; een nieuwe header geldt
    pas voor het volgende antwoord. Dus moet de URL veranderen, en dan kan hij
    ook meteen lang gecached worden - de site is er sneller van.

    Het stempel gaat mee in collectie.json, en dat bestand mag zelf niet
    gecached worden. De site plakt de waarde ongewijzigd achter publiek/duim/,
    dus er hoeft in de JavaScript niets te veranderen.
    """
    try:
        with open(pad, "rb") as fh:
            h = hashlib.md5(fh.read()).hexdigest()[:8]
    except OSError:
        return naam
    return f"{naam}?v={h}"


def duimnagels(records, hoezendir, doeldir, opnieuw=False):
    """Schaalt elke hoesfoto terug naar DUIM pixels op de lange zijde.

    Bewust geen vierkante uitsnede: een single is vierkant maar een opengeklapte
    hoes niet, en wie de verhouding weggooit kan een gatefold niet meer van een
    gewone hoes onderscheiden op het scherm.
    """
    os.makedirs(doeldir, exist_ok=True)
    gemaakt, overgeslagen, gemist = 0, 0, []
    for rec in records:
        for i, naam in enumerate(rec["fotos"], 1):
            bron = os.path.join(hoezendir, os.path.basename(naam))
            doelnaam = f"{rec['id']}-{i}.jpg"
            doel = os.path.join(doeldir, doelnaam)
            if os.path.exists(doel) and not opnieuw:
                rec.setdefault("duim", []).append(_met_stempel(doelnaam, doel))
                overgeslagen += 1
                continue
            rec.setdefault("duim", []).append(doelnaam)
            im = cv2.imread(bron)
            if im is None:
                gemist.append(naam)
                rec["duim"].pop()
                continue
            h, w = im.shape[:2]
            f = DUIM / max(h, w)
            if f < 1:
                im = cv2.resize(im, (round(w * f), round(h * f)),
                                interpolation=cv2.INTER_AREA)
            cv2.imwrite(doel, im, [cv2.IMWRITE_JPEG_QUALITY, KWALITEIT])
            rec["duim"][-1] = _met_stempel(doelnaam, doel)
            gemaakt += 1
    return gemaakt, overgeslagen, gemist


def bouw(csvpad, jsonpad, groepenpad, handmatigpad):
    with open(csvpad, encoding="utf-8-sig", newline="") as fh:
        rijen = list(csv.DictReader(fh))

    # het oordeel komt uit nauwkeurig.py, zodat de site precies hetzelfde
    # stempel toont als het rapport telt
    oordelen, beeldpunten = {}, {}
    try:
        from nauwkeurig import beoordeel
        platen = json.load(open(jsonpad, encoding="utf-8"))
        groepen = {r["id"]: r for r in json.load(open(groepenpad, encoding="utf-8"))}
        for p in platen:
            oordelen[str(p["id"])] = beoordeel(p, groepen.get(p["id"], {}))
            beeldpunten[str(p["id"])] = p.get("beeld_punten")
    except (OSError, ImportError, KeyError) as e:
        print(f"  (geen oordeel beschikbaar: {e})")

    uit = []
    for r in rijen:
        rid = (r.get("id") or "").strip()
        niveau, redenen = oordelen.get(rid, ("onbekend", []))

        def kies(*namen):
            for n in namen:
                v = (r.get(n) or "").strip()
                if v and v != "0":
                    return v
            return None

        uit.append({
            "id": rid,
            "artiest": kies("artiest_discogs", "gelezen_artist"),
            "titel": kies("titel_discogs", "gelezen_title"),
            "soort": kies("gelezen_soort") or "LP",
            "jaar": _getal(kies("jaar_discogs", "gelezen_year")),
            "label": kies("label_discogs", "gelezen_label"),
            "catno": kies("catno_discogs", "gelezen_catno"),
            "land": kies("land_discogs", "gelezen_country"),
            "genres": _lijst(r.get("genres"), ","),
            "formaat": kies("formats"),
            "tracks": _tracks(r.get("tracklist")),
            "prijs": _getal(r.get("vraagprijs")),
            "advies": kies("advies"),
            "markt": {
                "laagste": _getal(r.get("lowest_eur")),
                "vgplus": _getal(r.get("sug_vgplus")),
                "te_koop": _getal(r.get("num_for_sale")),
                "have": _getal(r.get("have")),
                "want": _getal(r.get("want")),
            },
            "discogs": kies("discogs_url"),
            "release_id": _getal(r.get("release_id")),
            "oordeel": niveau,
            "oordeel_reden": redenen,
            # hoeveel punten de eigen foto samenviel met de hoes op Discogs.
            # None = niet te toetsen (geen hoesfoto daar), en dat is iets anders
            # dan nul.
            "beeld_punten": beeldpunten.get(rid),
            "herkend_op": kies("gelezen_bron"),
            "advertentie": {"titel": kies("titel"), "tekst": kies("beschrijving")},
            "fotos": _lijst(r.get("fotos")),
        })
    uit.sort(key=lambda p: ((p["artiest"] or "~").lower(), (p["titel"] or "").lower()))

    # De onherkende platen zijn GROEPSrecords, geen plaatrecords: er is nooit
    # een artiest of titel van gemaakt, want dat is juist wat er misging. Wat er
    # wel is, is `koptekst` - de grootst gedrukte regels van de voorkant, en dat
    # is precies waaraan jij hem herkent als je hem zelf gaat opzoeken.
    rest = []
    if os.path.exists(handmatigpad):
        for h in json.load(open(handmatigpad, encoding="utf-8")):
            kop = h.get("koptekst") or []
            rest.append({
                "id": str(h.get("id") or ""),
                "titel": kop[0] if kop else None,
                "koptekst": kop[:4],
                "catno_kandidaten": (h.get("catno_kandidaten") or [])[:4],
                "jaar": h.get("jaar"),
                "land": h.get("land"),
                "reden": h.get("reden"),
                "fotos": h.get("fotos") or [],
            })
    return uit, rest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="uit/platen.csv")
    ap.add_argument("--json", default="uit/platen.json")
    ap.add_argument("--groepen", default="uit/groepen.json")
    ap.add_argument("--handmatig", default="uit/handmatig.json")
    ap.add_argument("--hoezen", default="hoezen")
    ap.add_argument("--uit", default="site/publiek")
    ap.add_argument("--opnieuw", action="store_true", help="duimnagels overdoen")
    a = ap.parse_args()

    platen, handmatig = bouw(a.csv, a.json, a.groepen, a.handmatig)
    print(f"{len(platen)} platen gelezen, {len(handmatig)} onherkend")

    # ook van de onherkende, want die moet je met het oog kunnen opzoeken
    gemaakt, over, gemist = duimnagels(platen + handmatig, a.hoezen,
                                       os.path.join(a.uit, "duim"), a.opnieuw)
    print(f"duimnagels: {gemaakt} gemaakt, {over} al aanwezig"
          + (f", {len(gemist)} niet gevonden" if gemist else ""))
    for n in gemist[:5]:
        print(f"    ontbreekt: {n}")

    telling = {}
    for p in platen:
        telling[p["oordeel"]] = telling.get(p["oordeel"], 0) + 1
    doc = {
        "versie": 1,
        "naam": "Mijn platenkast",
        "platen": platen,
        "handmatig": handmatig,
        "samenvatting": {
            "platen": len(platen),
            "onherkend": len(handmatig),
            "met_prijs": sum(1 for p in platen if p["prijs"]),
            "waarde": round(sum(p["prijs"] or 0 for p in platen), 2),
            "oordeel": telling,
        },
    }
    os.makedirs(a.uit, exist_ok=True)
    pad = os.path.join(a.uit, "collectie.json")
    with open(pad, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, separators=(",", ":"))

    mb = os.path.getsize(pad) / 1e6
    duimmb = sum(os.path.getsize(os.path.join(a.uit, "duim", f))
                 for f in os.listdir(os.path.join(a.uit, "duim"))) / 1e6
    print(f"\n{pad}  ({mb:.2f} MB)")
    print(f"{os.path.join(a.uit, 'duim')}  ({duimmb:.1f} MB)")
    print(f"samen {doc['samenvatting']['waarde']:.0f} euro over "
          f"{doc['samenvatting']['met_prijs']} platen met een prijs")


if __name__ == "__main__":
    main()
