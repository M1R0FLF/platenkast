#!/usr/bin/env python3
"""
leesfotos.py - RapidOCR over ELKE bijgeknipte foto, parallel over je kernen.

Waarom dit er is
----------------
Gemeten op de volledige set van 225 foto's liet tesseract 27% van de foto's op
nul tekens staan en 60% onder de 120. Daardoor rustte zowel het etiket
voor/achter als het groeperen in prep.py op ruis. RapidOCR haalt op dezelfde
hoezen wel tekst binnen: nul-tekenfoto's gingen van 62 naar 12.

LET OP: hier wordt niet gedraaid. Eerder stond op deze plek dat rechtop altijd
even goed of beter las, maar dat was gemeten op drie foto's die toevallig alle
drie rechtop stonden. Dat klopt dus niet. Hoezen die op hun kant liggen komen
er hier slecht uit; `herlees.py` probeert wel vier standen en haalt daar de
Tom Jones-single alsnog mee binnen (rechtop 3 woorden, kwartslag 7).

Draaien kost vier OCR-beurten per foto en dat is voor de hele set te duur.
Daarom hier niet, en in herlees.py alleen als het rechtop tegenvalt.

Snelheid
--------
RapidOCR is rekenwerk, geen netwerk, dus dit is het ene deel van de keten dat
je PC wel sneller kan maken. Eén proces deed ~5,5s per foto, twintig minuten
voor de set. Met een werker per kern is dat een paar minuten.

    py leesfotos.py                     alle kernen - 2
    py leesfotos.py --werkers 4         zuiniger
    py leesfotos.py --serieel           één proces, voor als er iets raars is

Herstartbaar: wat al in de cache staat wordt overgeslagen.
"""
import os, re, sys, json, glob, time, argparse, multiprocessing as mp
import cv2

MOTOR = None
MAXPX = 1800


def sorteer(indir):
    """Bestandsnamen op de cijfers erin, niet alfabetisch: er staan twee
    naamstijlen door elkaar en een liggend streepje sorteert na een cijfer."""
    return sorted({os.path.normcase(f): f for f in
                   sum((glob.glob(os.path.join(indir, e))
                        for e in ("*.jpg", "*.jpeg", "*.png")), [])
                   if "contactvel" not in f.lower()}.values(),
                  key=lambda f: ((0, re.sub(r"\D", "", os.path.basename(f)).ljust(20, "0"))
                                 if len(re.sub(r"\D", "", os.path.basename(f))) >= 12
                                 else (1, os.path.basename(f))))


def init(maxpx):
    """Elke werker krijgt zijn eigen model. Dat kost geheugen maar geen tijd:
    laden duurt een paar seconden, daarna leest hij honderden foto's."""
    global MOTOR, MAXPX
    MAXPX = maxpx
    # onnxruntime pakt anders zelf alle kernen, en dan vechten de werkers
    # onderling om dezelfde rekentijd.
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    from rapidocr_onnxruntime import RapidOCR
    MOTOR = RapidOCR()


def lees(img):
    """Geeft vakken terug als dicts met genormaliseerde plaats en hoogte."""
    try:
        res, _ = MOTOR(img)
    except Exception:
        return []
    if not res:
        return []
    H, W = img.shape[:2]
    uit = []
    for vak in res:
        doos, tekst = vak[0], vak[1]
        score = vak[2] if len(vak) > 2 else 0.0
        ys = [p[1] for p in doos]
        xs = [p[0] for p in doos]
        uit.append({"y": round(min(ys) / H, 4), "x": round(min(xs) / W, 4),
                    "h": round((max(ys) - min(ys)) / H, 4),
                    "t": tekst, "s": round(float(score), 3)})
    uit.sort(key=lambda v: (round(v["y"] * H / 25), v["x"]))
    return uit


def tekst_van(vakken):
    return "\n".join(v["t"] for v in vakken)


def stroken(img):
    """Boven- en onderrand vergroot: daar staat het catalogusnummer."""
    h, w = img.shape[:2]
    uit = []
    for y0, y1 in ((0.0, 0.16), (0.84, 1.0)):
        s = img[int(h * y0):int(h * y1), :]
        if s.size == 0:
            continue
        f = 2200.0 / s.shape[1]
        if f > 1:
            s = cv2.resize(s, (int(s.shape[1] * f), int(s.shape[0] * f)),
                           interpolation=cv2.INTER_CUBIC)
        uit.append(tekst_van(lees(s)))
    return "\n".join(uit)


def doe_een(pad):
    """Draait in een werker. Geeft (sleutel, resultaat) terug."""
    naam = os.path.basename(pad)
    sleutel = f"{naam}:{os.path.getsize(pad)}"
    img = cv2.imread(pad)
    if img is None:
        return sleutel, {"t": "", "h": "", "vakken": [], "fout": "onleesbaar"}
    f = MAXPX / max(img.shape[:2])
    if f < 1:
        img = cv2.resize(img, (int(img.shape[1] * f), int(img.shape[0] * f)),
                         interpolation=cv2.INTER_AREA)
    vakken = lees(img)
    return sleutel, {"t": tekst_van(vakken), "h": stroken(img), "vakken": vakken}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--indir", default="bijgeknipt")
    ap.add_argument("--cache", default="ocr2_cache.json")
    ap.add_argument("--max", type=int, default=0)
    ap.add_argument("--maxpx", type=int, default=1800)
    ap.add_argument("--werkers", type=int, default=0,
                    help="0 = 6, of minder als je er minder hebt")
    ap.add_argument("--serieel", action="store_true")
    a = ap.parse_args()

    bestanden = sorteer(a.indir)
    if a.max:
        bestanden = bestanden[:a.max]

    cache = {}
    if os.path.exists(a.cache):
        try:
            cache = json.load(open(a.cache, encoding="utf-8"))
        except Exception:
            cache = {}

    todo = [f for f in bestanden
            if f"{os.path.basename(f)}:{os.path.getsize(f)}" not in cache]
    print(f"{len(bestanden)} foto's, {len(cache)} al gelezen, {len(todo)} te gaan.")
    if not todo:
        print("niets te doen.")
        return

    # Gemeten: 18 werkers was met 10s/foto TRAGER dan 1 werker met 5,5s/foto.
    # Elke werker laadt zijn eigen model, en dat laden wint het van het lezen.
    # Zes is het punt waar het laden nog terugverdiend wordt.
    werkers = 1 if a.serieel else (a.werkers or min(6, os.cpu_count() or 1))
    werkers = min(werkers, len(todo))
    print(f"{werkers} werker(s) op {os.cpu_count()} kernen\n", flush=True)

    t0, gedaan = time.time(), 0

    def bewaar():
        json.dump(cache, open(a.cache, "w", encoding="utf-8"), ensure_ascii=False)

    if werkers == 1:
        init(a.maxpx)
        for pad in todo:
            sleutel, res = doe_een(pad)
            cache[sleutel] = res
            gedaan += 1
            bewaar()
            print(f"[{gedaan}/{len(todo)}] {os.path.basename(pad):<28} "
                  f"{len(re.sub(r'\s','',res['t'])):>5} tekens "
                  f"{(time.time()-t0)/gedaan:.1f}s/foto", flush=True)
    else:
        with mp.Pool(werkers, initializer=init, initargs=(a.maxpx,)) as pool:
            for sleutel, res in pool.imap_unordered(doe_een, todo, chunksize=1):
                cache[sleutel] = res
                gedaan += 1
                if gedaan % 10 == 0 or gedaan == len(todo):
                    bewaar()
                print(f"[{gedaan}/{len(todo)}] {sleutel.split(':')[0]:<28} "
                      f"{len(re.sub(r'\s','',res['t'])):>5} tekens "
                      f"{(time.time()-t0)/gedaan:.2f}s/foto", flush=True)
        bewaar()

    print(f"\nklaar: {gedaan} gelezen in {int(time.time()-t0)}s -> {a.cache}")


if __name__ == "__main__":
    mp.freeze_support()
    main()
