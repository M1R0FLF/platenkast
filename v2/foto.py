#!/usr/bin/env python3
"""
foto.py - alles wat met één foto gebeurt, in één keer: uitsnijden, rechtzetten
en lezen.

In v1 waren dit drie losse stappen over de hele set (crop_sleeves, leesfotos,
herlees). Het uitsnijden schaalde daar terug naar 1600 pixels en daar ging
klein drukwerk aan kapot: "R. / BANK / DANR" werd op de originele foto
"Gilbert O'Sullivan / HIMSELF / MAM-SS501". Hier wordt op 3200 gesneden.

Het snijden en rechtzetten zelf staat in knip.py. Dat stond eerst hier, en het
was op twee punten mis:

  - de uitsnede werd weggegooid als hij 1:2 was, want "een gatefold ligt breder
    dan hoog". Dat geldt voor het EINDRESULTAAT, niet voor de foto: een
    opengeklapte hoes ligt net zo vaak op zijn kant op de vloer.
  - de stand werd bepaald door in alle vier de richtingen de hele hoes te lezen
    en de woorden te tellen. Vier keer het dure werk, en bij een hoes met weinig
    tekst kwam het antwoord uit ruis.

Deze module draait in een werkproces. Het is het enige deel van de keten dat
echt rekenwerk is, en dus het enige deel dat sneller wordt van meer kernen.
"""
import os, re, glob

# Deze moeten VOOR de import van cv2 en onnxruntime staan, anders lezen die hun
# draadinstelling al uit en veranderen ze niet meer.
#
# Gemeten zonder deze regels: zes werkprocessen hielden negentien kernen bezig
# en haalden samen zes foto's per minuut, ruim 190 CPU-seconden per foto. Elk
# proces startte zelf ook nog eens een handvol draden, en die stonden vooral op
# elkaar te wachten. Met een draad per proces doet elk proces zijn eigen foto
# en zijn zes processen ook echt zes keer zo snel.
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
           "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_v, "1")

import cv2

cv2.setNumThreads(1)

import knip
from knip import autolevel, motor

WOORD = re.compile(r"[A-Za-z]{4,}")


def _vakken(img):
    try:
        res, _ = motor()(img)
    except Exception:
        return []
    if not res:
        return []
    H, W = img.shape[:2]
    uit = []
    for vak in res:
        doos, tekst = vak[0], vak[1]
        ys = [p[1] for p in doos]
        xs = [p[0] for p in doos]
        uit.append({"y": round(min(ys) / H, 4), "x": round(min(xs) / W, 4),
                    "h": round((max(ys) - min(ys)) / H, 4), "t": tekst,
                    # breedte/hoogte van het tekstvak in pixels: bij een foto
                    # die op zijn kant ligt staan de vakken rechtop
                    "vh": round((max(xs) - min(xs)) / max(max(ys) - min(ys), 1), 2)})
    uit.sort(key=lambda v: (round(v["y"] * H / 25), v["x"]))
    return uit


def _tekst(vakken):
    return "\n".join(v["t"] for v in vakken)


def _stroken(img):
    """Boven- en onderrand vergroot: daar staat het catalogusnummer."""
    h, w = img.shape[:2]
    uit = []
    for y0, y1 in ((0.0, 0.16), (0.84, 1.0)):
        s = img[int(h * y0):int(h * y1), :]
        if s.size == 0:
            continue
        f = 2400.0 / s.shape[1]
        if f > 1:
            s = cv2.resize(s, (int(s.shape[1] * f), int(s.shape[0] * f)),
                           interpolation=cv2.INTER_CUBIC)
        uit.append(_tekst(_vakken(s)))
    return "\n".join(uit)


def _cache_open(pad):
    import sqlite3
    os.makedirs(os.path.dirname(pad) or ".", exist_ok=True)
    db = sqlite3.connect(pad)
    db.execute("CREATE TABLE IF NOT EXISTS ocr (sleutel TEXT PRIMARY KEY, waarde TEXT)")
    db.commit()
    return db


def verwerk(taak):
    """Eén foto van begin tot eind: uitsnijden, rechtzetten, lezen.

    taak = (pad, hoezendir, zijde, leespx, opnieuw, cachepad)

    Het lezen wordt bewaard. Zonder die cache kostte elke herstart opnieuw een
    half uur OCR, terwijl er aan de foto's niets veranderd was.
    """
    import json as _json
    pad, hoezendir, zijde, leespx, opnieuw, cachepad = taak
    db = _cache_open(cachepad) if cachepad else None
    sleutel = (f"{os.path.basename(pad)}:{os.path.getsize(pad)}:"
               f"{zijde}:{leespx}:s{knip.VERSIE}")
    if db is not None and not opnieuw:
        r = db.execute("SELECT waarde FROM ocr WHERE sleutel=?", (sleutel,)).fetchone()
        if r:
            uit = _json.loads(r[0])
            if os.path.exists(uit.get("pad", "")):
                db.close()
                return uit
    uit = _verwerk(pad, hoezendir, zijde, leespx, opnieuw)
    if db is not None and not uit.get("fout"):
        db.execute("INSERT OR REPLACE INTO ocr VALUES (?,?)",
                   (sleutel, _json.dumps(uit, ensure_ascii=False)))
        db.commit()
    if db is not None:
        db.close()
    return uit


def _verwerk(pad, hoezendir, zijde, leespx, opnieuw):
    naam = os.path.splitext(os.path.basename(pad))[0]
    doel = os.path.join(hoezendir, naam + ".jpg")

    # Een bewaarde uitsnede is alleen bruikbaar als hij van dezelfde snijcode
    # komt. Zonder deze stempel zou een verbeterde snijmethode stilletjes de
    # oude, slechtere uitsnedes blijven hergebruiken en zou niemand merken dat
    # de verbetering nooit is toegepast.
    stempel = os.path.join(hoezendir, ".snijversie")
    actueel = (os.path.exists(stempel)
               and open(stempel, encoding="utf-8").read().strip() == str(knip.VERSIE))
    hergebruik = actueel and not opnieuw and os.path.exists(doel)
    if hergebruik:
        # de bewaarde hoes is al gesneden en al rechtgezet
        hoes = cv2.imread(doel)
        if hoes is None:
            return {"naam": naam, "fout": "onleesbaar"}
        gesneden, stand, cijfer, bron, zeker = True, "0", None, "bewaard", True
    else:
        ruw = cv2.imread(pad)
        if ruw is None:
            return {"naam": naam, "fout": "onleesbaar"}
        hoes, cijfer, bron = knip.snijd(ruw, zijde)
        if hoes is None:
            # Uitsnijden mislukt: de hele foto gebruiken is beter dan niets.
            # In v1 ging dat via redden.py als aparte stap achteraf.
            hoes, gesneden = ruw, False
        else:
            gesneden = True
        # Rechtzetten vóór het lezen en vóór het bewaren, zodat de OCR en de
        # foto voor de advertentie allebei van dezelfde rechte hoes komen.
        hoes, stand, waarom, zeker = knip.rechtop(hoes)
        hoes = autolevel(hoes)
        os.makedirs(hoezendir, exist_ok=True)
        cv2.imwrite(doel, hoes, [cv2.IMWRITE_JPEG_QUALITY, 92])
        if not actueel:
            open(stempel, "w", encoding="utf-8").write(str(knip.VERSIE))

    # Resolutie kost tijd: 6,8s op 1200 pixels tegen 10,4s op 3200. Daarom
    # eerst op 1800, en alleen als dat weinig oplevert nog een keer op volle
    # resolutie. Dat laatste is waar "R. / BANK / DANR" veranderde in
    # "Gilbert O'Sullivan / HIMSELF / MAM-SS501".
    def _schaal(px):
        f = px / max(hoes.shape[:2])
        if f >= 1:
            return hoes
        return cv2.resize(hoes, (int(hoes.shape[1] * f), int(hoes.shape[0] * f)),
                          interpolation=cv2.INTER_AREA)

    lees = _schaal(min(1800, leespx))
    vakken = _vakken(lees)
    if leespx > 1800 and len(WOORD.findall(_tekst(vakken))) < 14:
        groot = _schaal(leespx)
        v2 = _vakken(groot)
        if len(_tekst(v2)) > len(_tekst(vakken)):
            lees, vakken = groot, v2

    # De hoekstroken kosten nog eens vijf seconden. Alleen nodig als het
    # catalogusnummer niet al in de gewone tekst staat, en dat scheelt de helft
    # van de foto's.
    from velden import uit_tekst
    tekst = _tekst(vakken)
    hoek = "" if uit_tekst(tekst)["catno_kandidaten"] else _stroken(lees)

    h, w = hoes.shape[:2]
    return {
        "naam": naam, "bestand": os.path.basename(doel), "pad": doel,
        "breedte": w, "hoogte": h,
        "breed": w / h > 1.6,          # opengeklapte hoes
        "gesneden": gesneden, "stand": stand,
        # cijfer en bron zeggen hoe de uitsnede tot stand kwam; `rechtop` zegt
        # of de kop-staartvraag echt beantwoord is of dat de hoes alleen maar
        # is blijven liggen zoals hij lag. Dat laatste is geen fout maar een
        # onbekende, en hoort als zodanig naar buiten te komen.
        "cijfer": cijfer, "bron": bron, "rechtop": zeker,
        "t": tekst, "h": hoek, "vakken": vakken,
    }


def originelen(indir):
    """Bestandsnamen op de cijfers erin, niet alfabetisch: er staan twee
    naamstijlen door elkaar en een streepje sorteert na een cijfer."""
    paden = {os.path.normcase(f): f for f in
             sum((glob.glob(os.path.join(indir, e))
                  for e in ("*.jpg", "*.jpeg", "*.png", "*.JPG")), [])
             if "contactvel" not in f.lower()}
    return sorted(paden.values(),
                  key=lambda f: ((0, re.sub(r"\D", "", os.path.basename(f)).ljust(20, "0"))
                                 if len(re.sub(r"\D", "", os.path.basename(f))) >= 12
                                 else (1, os.path.basename(f))))
