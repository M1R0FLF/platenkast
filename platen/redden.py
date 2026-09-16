#!/usr/bin/env python3
"""
redden.py - haalt de foto's terug die het bijknippen niet aankon.

Voor OCR hoeft een hoes niet netjes uitgesneden te zijn. Deze foto's gaan dus
gewoon als geheel de keten in, alleen verkleind en rechtgezet. Beter een ruwe
achterkant met een leesbare tracklist dan een plaat zonder achterkant.

    py redden.py .\\fotos .\\bijgeknipt --tesseract "C:\\Program Files\\Tesseract-OCR\\tesseract.exe"

Bestanden krijgen het achtervoegsel _ruw, zodat je in het contactvel meteen ziet
welke niet netjes uitgesneden zijn.
"""
import os, sys, glob, argparse, subprocess, tempfile, csv, io
import cv2
import numpy as np

TESS = "tesseract"


def _score(img):
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as t:
        cv2.imwrite(t.name, img)
    try:
        r = subprocess.run([TESS, t.name, "-", "-l", "eng", "--psm", "3", "tsv"],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=60)
    except Exception:
        return 0.0
    finally:
        try:
            os.unlink(t.name)
        except OSError:
            pass
    tot = 0.0
    for row in csv.DictReader(io.StringIO(r.stdout), delimiter="\t",
                              quoting=csv.QUOTE_NONE):
        try:
            c = float(row.get("conf", -1))
        except (TypeError, ValueError):
            continue
        w = (row.get("text") or "").strip()
        if c >= 60 and len(w) >= 3 and any(ch.isalpha() for ch in w):
            tot += c
    return tot


def rechtzetten(img):
    f = 1000.0 / max(img.shape[:2])
    k = cv2.resize(img, (int(img.shape[1] * f), int(img.shape[0] * f)),
                   interpolation=cv2.INTER_AREA) if f < 1 else img
    s0 = _score(k)
    s180 = _score(cv2.rotate(k, cv2.ROTATE_180))
    if s180 > max(s0, 1) * 1.6 and s180 >= 200:
        return cv2.rotate(img, cv2.ROTATE_180)
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("origineel"); ap.add_argument("bijgeknipt")
    ap.add_argument("--lijst", default=None,
                    help="standaard bijgeknipt\\handmatig.txt")
    ap.add_argument("--tesseract", default="tesseract")
    ap.add_argument("--size", type=int, default=1600)
    ap.add_argument("--rand", type=float, default=4.0,
                    help="procent van de buitenrand wegsnijden")
    a = ap.parse_args()

    global TESS
    TESS = a.tesseract
    lijst = a.lijst or os.path.join(a.bijgeknipt, "handmatig.txt")
    if not os.path.exists(lijst):
        sys.exit(f"{lijst} bestaat niet. Draai eerst crop_sleeves.py.")

    namen = [l.strip() for l in open(lijst, encoding="utf-8") if l.strip()]
    print(f"{len(namen)} foto's terug te halen\n")

    gered = 0
    for naam in namen:
        treffers = glob.glob(os.path.join(a.origineel, naam + ".*"))
        if not treffers:
            print(f"  niet gevonden : {naam}")
            continue
        img = cv2.imread(treffers[0])
        if img is None:
            print(f"  onleesbaar    : {naam}")
            continue

        h, w = img.shape[:2]
        m = a.rand / 100.0
        img = img[int(h * m):int(h * (1 - m)), int(w * m):int(w * (1 - m))]

        img = rechtzetten(img)
        h, w = img.shape[:2]
        f = min(1.0, a.size / max(h, w))
        img = cv2.resize(img, (int(w * f), int(h * f)), interpolation=cv2.INTER_AREA)

        uit = os.path.join(a.bijgeknipt, naam + "_ruw.jpg")
        cv2.imwrite(uit, img, [cv2.IMWRITE_JPEG_QUALITY, 92])
        print(f"  gered         : {naam}")
        gered += 1

    print(f"\n{gered} van {len(namen)} teruggezet in {a.bijgeknipt}")
    print("Draai nu opnieuw:  run.ps1 -Stap prep   en daarna  run.ps1 -Stap auto -Opnieuw")


if __name__ == "__main__":
    main()
