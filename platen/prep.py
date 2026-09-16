#!/usr/bin/env python3
"""
prep.py - bereidt het uitlezen voor zodat Claude Code zo min mogelijk beeld
hoeft te bekijken.

Doet lokaal, gratis:
  1. tesseract-OCR over elke bijgeknipte hoes
  2. voorkant/achterkant herkennen aan de hoeveelheid tekst
  3. groeperen per plaat
  4. catalogusnummer, land, jaar en streepjescode uit de tekst vissen
  5. een 'kit' met verkleinde beelden klaarzetten voor de gevallen waar het
     toch nodig is

    py prep.py .\\bijgeknipt .\\kit ruw.json --tesseract "C:\\Program Files\\Tesseract-OCR\\tesseract.exe"

Waarom dit scheelt: beeldkosten lopen ongeveer met breedte maal hoogte gedeeld
door 750. Een hoes van 1568 pixels kost zo'n 3300 tokens, dezelfde hoes op 600
pixels nog geen 500. Een voorkant heeft die scherpte niet nodig, een achterkant
alleen in de strook waar het catalogusnummer staat.
"""
import os, re, sys, json, glob, argparse, subprocess, tempfile
import cv2
import numpy as np

TESS = "tesseract"


def ocr_img(img, psm=3):
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as t:
        cv2.imwrite(t.name, img)
    try:
        return ocr(t.name, psm)
    finally:
        try:
            os.unlink(t.name)
        except OSError:
            pass


def hoek_ocr(img):
    """De bovenste strook, vergroot, met leesstand voor losse fragmenten.
    Het catalogusnummer staat daar meestal klein in een kadertje, en de
    gewone bladschikking van tesseract slaat zulke blokjes over."""
    h, w = img.shape[:2]
    uit = []
    for y0, y1 in ((0.0, 0.15), (0.85, 1.0)):
        strook = img[int(h * y0):int(h * y1), :]
        if strook.size == 0:
            continue
        f = 2000.0 / strook.shape[1]
        groot = cv2.resize(strook, (int(strook.shape[1] * f), int(strook.shape[0] * f)),
                           interpolation=cv2.INTER_CUBIC)
        for psm in (11, 12):
            uit.append(ocr_img(groot, psm))
    return "\n".join(uit)


def ocr(path, psm=3):
    try:
        r = subprocess.run([TESS, path, "-", "-l", "eng", "--psm", str(psm)],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=60)
        return r.stdout
    except Exception:
        return ""


def tokens(w, h):
    """Ruwe schatting van de beeldkosten, zoals de modellen die rekenen."""
    s = min(1.0, 1568 / max(w, h))
    return int((w * s) * (h * s) / 750)


# ------------------------------------------------------------- uit de tekst --

LANDEN = [("west germany", "West Germany"), ("germany", "Germany"),
          ("belgium", "Belgium"), ("belgie", "Belgium"), ("belgië", "Belgium"),
          ("holland", "Netherlands"), ("netherlands", "Netherlands"),
          ("france", "France"), ("italy", "Italy"), ("italie", "Italy"),
          ("england", "UK"), ("great britain", "UK"), ("u.k", "UK"),
          ("spain", "Spain"), ("sweden", "Sweden"), ("u.s.a", "US"),
          ("usa", "US"), ("united states", "US")]

CATNO = re.compile(r"""(?x)
    \b(
        [A-Z]{2,6}[ .\-]?\d{3,6}(?:[ \-/]\d{1,4})?     # SHVL 804, WB SOUND 5034
      | \d{2,3}[ ]\d{3}[ ]?-?[ ]?\d(?:[ ]?[A-Z]{1,3}\d?)?   # 415 253-1 GH2
      | \d?[ ]?[A-Z]\d{3}-\d{4,6}                       # 4 C058-90264, C058-90264
      | \d{2}\.[A-Z]{2}\.\d{3}\.\d{3}                   # 45.VB.140.310
      | \d{2,3}\.\d{3}\b                                # 101.109
      | \b\d{5,8}\b                                     # 212001, 2315321, 82854
    )\b""")

# RapidOCR plakt alles binnen één tekstvak aaneen: STEREO2315321,
# Stereo-Mono9199534. Het catalogusnummer zit dan midden in een woord en geen
# enkel patroon met \b ervoor vindt het nog. Deze woorden staan er standaard
# tegenaan gedrukt op een hoes.
PLAKKERS = re.compile(r"(?i)\b(stereo|mono|face|side|kant|rpm|nr|no)[ .\-]?(?=\d)")


def ontplak(t):
    return PLAKKERS.sub(r"\1 ", t or "")

RUIS = {"STEREO", "MONO", "SIDE", "RECORDS", "RECORD", "PRINTED", "MADE",
        "MANUFACTURED", "RPM", "BMI", "ASCAP", "GEMA", "SABAM", "LTD",
        "LIMITED", "COPYRIGHT", "PRODUCED", "ARRANGED"}


def uit_tekst(t):
    t = ontplak(t)
    laag = t.lower()
    land = next((n for k, n in LANDEN
                 if re.search(r"(printed|made|manufactured|pressed)[^.\n]{0,40}" + re.escape(k), laag)
                 or re.search(r"\b" + re.escape(k) + r"\b", laag)), None)

    jaren = [int(y) for y in re.findall(r"\b(19[4-9]\d)\b", t)]
    jaar = max(set(jaren), key=jaren.count) if jaren else None

    plat = re.sub(r"[ \-]", "", t)
    bc = re.search(r"\b(\d{12,13})\b", plat)

    kand, gezien = [], set()
    for m in CATNO.finditer(t):
        v = " ".join(m.group(1).split())
        if v.upper() in RUIS or any(w in v.upper() for w in ("19", "20")) and v.isdigit() and len(v) == 4:
            continue
        if v.upper() not in gezien:
            gezien.add(v.upper())
            kand.append(v)
    return {"land": land, "jaar": jaar, "barcode": bc.group(1) if bc else None,
            "catno_kandidaten": kand[:6]}


# ------------------------------------------------------------------- beeld --

def schrijf_kit(src, kitdir, stam, rol):
    """Verkleint slim per rol. Geeft pad en geschatte kosten terug."""
    im = cv2.imread(src)
    if im is None:
        return {}
    h, w = im.shape[:2]
    uit = {}

    def bewaar(img, naam, q=85):
        p = os.path.join(kitdir, naam)
        cv2.imwrite(p, img, [cv2.IMWRITE_JPEG_QUALITY, q])
        return {"pad": p.replace("\\", "/"),
                "tokens": tokens(img.shape[1], img.shape[0])}

    if rol == "front":
        f = 600 / max(h, w)                      # titel is groot gedrukt
        klein = cv2.resize(im, (int(w * f), int(h * f)), interpolation=cv2.INTER_AREA)
        uit["voor"] = bewaar(klein, f"{stam}_voor.jpg")
    else:
        f = min(1.0, 1100 / max(h, w))           # leesbaar, niet meer dan dat
        klein = cv2.resize(im, (int(w * f), int(h * f)), interpolation=cv2.INTER_AREA)
        uit["achter"] = bewaar(klein, f"{stam}_achter.jpg")
        # bovenste strook op volle scherpte: daar staat het catalogusnummer
        strook = im[0:int(h * 0.13), :]
        if strook.size:
            fs = min(1.0, 1500 / strook.shape[1])
            strook = cv2.resize(strook, (int(strook.shape[1] * fs),
                                         int(strook.shape[0] * fs)))
            uit["hoek"] = bewaar(strook, f"{stam}_hoek.jpg", 92)
    return uit


# -------------------------------------------------------------------- main --

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("indir"); ap.add_argument("kitdir")
    ap.add_argument("uitvoer", nargs="?", default="ruw.json")
    ap.add_argument("--tesseract", default="tesseract")
    ap.add_argument("--geen-cache", action="store_true", dest="geen_cache",
                    help="negeer de bewaarde OCR en lees alles opnieuw")
    ap.add_argument("--drempel", type=int, default=120,
                    help="aantal tekens waarboven een foto als achterkant telt")
    a = ap.parse_args()

    global TESS
    TESS = a.tesseract
    os.makedirs(a.kitdir, exist_ok=True)

    cachepad = a.uitvoer.replace(".json", "") + "_ocrcache.json"
    cache = {}
    if os.path.exists(cachepad) and not a.geen_cache:
        try:
            cache = json.load(open(cachepad, encoding="utf-8"))
        except Exception:
            cache = {}

    bestanden = sorted({os.path.normcase(f): f for f in
                        sum((glob.glob(os.path.join(a.indir, e))
                             for e in ("*.jpg", "*.jpeg", "*.png")), [])
                        if "contactvel" not in f.lower()}.values(),
                       key=lambda f: ((0, re.sub(r"\D", "", os.path.basename(f)).ljust(20, "0"))
                                      if len(re.sub(r"\D", "", os.path.basename(f))) >= 12
                                      else (1, os.path.basename(f))))
    if not bestanden:
        sys.exit("Geen bijgeknipte foto's gevonden.")

    print(f"{len(bestanden)} foto's, OCR draait lokaal...\n")
    info = {}
    for f in bestanden:
        im = cv2.imread(f)
        naam = os.path.basename(f)
        breed = im is not None and im.shape[1] / im.shape[0] > 1.4
        sleutel = f"{naam}:{os.path.getsize(f)}"
        if sleutel in cache:
            t, hoek = cache[sleutel]["t"], cache[sleutel]["h"]
        else:
            t = ocr(f)
            hoek = "" if breed else hoek_ocr(im)
            cache[sleutel] = {"t": t, "h": hoek}
        n = len(re.sub(r"\s", "", t))
        soort = "gatefold" if breed else ("back" if n >= a.drempel else "front")
        info[f] = {"naam": naam, "soort": soort, "tekens": n, "tekst": t,
                   "hoek": hoek}

    json.dump(cache, open(cachepad, "w", encoding="utf-8"), ensure_ascii=False)

    # Een vaste drempel werkt niet. Op een matte of donkere achterkant haalt de
    # OCR soms maar tachtig tekens, en dan telt die als voorkant. Gevolg: twee
    # voorkanten na elkaar, dus twee losse platen zonder tracklist.
    # Een achterkant is vooral een PLAATSELIJK MAXIMUM: meer tekst dan de foto
    # ervoor en die erna. Dat klopt of de hoes nu licht of donker is.
    ntek = [info[f]["tekens"] for f in bestanden]
    for i, f in enumerate(bestanden):
        if info[f]["soort"] == "gatefold":
            continue
        links = ntek[i - 1] if i > 0 else -1
        rechts = ntek[i + 1] if i + 1 < len(ntek) else -1
        lokaal_max = ntek[i] >= 25 and ntek[i] > links and ntek[i] >= rechts
        info[f]["soort"] = "back" if (ntek[i] >= a.drempel or lokaal_max) else "front"

    # Nooit twee achterkanten naast elkaar: de zwakste wordt weer voorkant.
    for i in range(len(bestanden) - 1):
        a1, a2 = bestanden[i], bestanden[i + 1]
        if info[a1]["soort"] == info[a2]["soort"] == "back":
            zwak = a1 if info[a1]["tekens"] <= info[a2]["tekens"] else a2
            info[zwak]["soort"] = "front"

    for f in bestanden:
        print(f"  {info[f]['naam']:<30} {info[f]['soort']:<9} {info[f]['tekens']:>5} tekens")

    # groeperen: nieuwe plaat zodra een soort terugkomt
    groepen, cur, gezien = [], [], set()
    for f in bestanden:
        k = info[f]["soort"]
        if k in ("front", "back") and k in gezien:
            groepen.append(cur); cur, gezien = [], set()
        if k in ("front", "back"):
            gezien.add(k)
        cur.append(f)
    if cur:
        groepen.append(cur)

    uit, kosten = [], 0
    for g in groepen:
        stam = re.sub(r"\D", "", os.path.basename(g[0]))[-6:] or os.path.basename(g[0])[:6]
        achter = [f for f in g if info[f]["soort"] == "back"]
        voor = [f for f in g if info[f]["soort"] == "front"]
        tekst_achter = "\n".join(info[f]["tekst"] for f in achter).strip()
        tekst_voor = "\n".join(info[f]["tekst"] for f in voor).strip()
        hoektekst = "\n".join(info[f]["hoek"] for f in g).strip()
        velden = uit_tekst(tekst_achter + "\n" + tekst_voor + "\n" + hoektekst)
        # hoekvondsten vooraan: daar staat het echte catalogusnummer
        hoek_kand = uit_tekst(hoektekst)["catno_kandidaten"]
        velden["catno_kandidaten"] = hoek_kand + [c for c in velden["catno_kandidaten"]
                                                  if c not in hoek_kand]

        beelden = {}
        for f in voor[:1]:
            beelden.update(schrijf_kit(f, a.kitdir, stam, "front"))
        for f in achter[:1]:
            beelden.update(schrijf_kit(f, a.kitdir, stam, "back"))
        kosten += sum(b["tokens"] for b in beelden.values())

        goed = (len(re.sub(r"\s", "", tekst_achter)) >= 350
                and bool(velden["catno_kandidaten"]) and bool(velden["land"]))
        uit.append({
            "id": stam,
            "fotos": [os.path.basename(f) for f in g],
            "ocr_kwaliteit": "goed" if goed else "zwak",
            "ocr_achterkant": tekst_achter[:3000],
            "ocr_voorkant": tekst_voor[:600],
            "ocr_hoekstrook": hoektekst[:800],
            **velden,
            "beelden": beelden,
        })

    json.dump(uit, open(a.uitvoer, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    g = sum(1 for r in uit if r["ocr_kwaliteit"] == "goed")
    print(f"\n{len(groepen)} platen -> {a.uitvoer}")
    print(f"{g} met bruikbare OCR (tekst volstaat), {len(uit)-g} waar beeld nodig is")
    print(f"beeldkosten als je alles zou bekijken: ~{kosten:,} tokens "
          f"({kosten//max(len(uit),1):,} per plaat)")


if __name__ == "__main__":
    main()
