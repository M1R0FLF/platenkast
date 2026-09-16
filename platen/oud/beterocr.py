#!/usr/bin/env python3
"""
beterocr.py - leest de overgebleven platen opnieuw met RapidOCR, een neuraal
OCR-model dat lokaal draait.

Tesseract werkt met drempelwaarden en haalt op donkere of glanzende hoezen
nauwelijks iets binnen. RapidOCR gebruikt een netwerk dat tekstvakken opspoort
en dan pas leest, en dat werkt daar wel. Gemeten op de testhoezen: tesseract
vond geen enkel catalogusnummer, RapidOCR vond WB SOUND 5034 en 212001.

Alles blijft op je eigen PC. Geen account, geen sleutel, geen kaart. Wel traag:
reken op vier tot tien seconden per foto.

    py -m pip install rapidocr-onnxruntime
    py beterocr.py voor_claude.json ruw_beter.json --bijgeknipt .\\bijgeknipt
    py automatch.py ruw_beter.json platen.json --rest voor_claude.json

Werkt onnxruntime niet op jouw Python-versie, dan is die te nieuw. Installeer
Python 3.12 ernaast en draai dit script daarmee.
"""
import os, re, sys, json, glob, argparse, time
import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prep import uit_tekst          # dezelfde regels voor catno, land, jaar


def maak_motor():
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        sys.exit("rapidocr-onnxruntime ontbreekt.\n"
                 "  py -m pip install rapidocr-onnxruntime\n"
                 "Faalt dat op onnxruntime, dan is je Python te nieuw. "
                 "Installeer Python 3.12 ernaast.")
    return RapidOCR()


def lees(motor, img):
    """Geeft de tekst terug, regels op leesvolgorde van boven naar onder."""
    try:
        res, _ = motor(img)
    except Exception:
        return ""
    if not res:
        return ""
    regels = []
    for vak in res:
        doos, tekst = vak[0], vak[1]
        y = min(p[1] for p in doos)
        x = min(p[0] for p in doos)
        regels.append((y, x, tekst))
    regels.sort(key=lambda r: (round(r[0] / 25), r[1]))
    return "\n".join(r[2] for r in regels)


def hoekstroken(motor, img):
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
        uit.append(lees(motor, s))
    return "\n".join(uit)


def zoek(bijgeknipt, naam):
    for kand in (naam, os.path.splitext(naam)[0]):
        for p in glob.glob(os.path.join(bijgeknipt, kand + ".*")):
            return p
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("invoer", nargs="?", default="voor_claude.json")
    ap.add_argument("uitvoer", nargs="?", default="ruw_beter.json")
    ap.add_argument("--bijgeknipt", default="bijgeknipt")
    ap.add_argument("--max", type=int, default=0)
    ap.add_argument("--maxpx", type=int, default=1800)
    a = ap.parse_args()

    platen = json.load(open(a.invoer, encoding="utf-8"))
    if a.max:
        platen = platen[:a.max]
    print(f"{len(platen)} platen opnieuw lezen. Reken op "
          f"{len(platen) * 12 // 60 + 1} minuten.\n")

    motor = maak_motor()
    uit, beter, nieuwe_nrs = [], 0, 0
    t0 = time.time()

    for i, rec in enumerate(platen, 1):
        teksten, hoeken = [], []
        for naam in (rec.get("fotos") or []):
            pad = zoek(a.bijgeknipt, naam)
            if not pad:
                continue
            img = cv2.imread(pad)
            if img is None:
                continue
            f = a.maxpx / max(img.shape[:2])
            if f < 1:
                img = cv2.resize(img, (int(img.shape[1] * f), int(img.shape[0] * f)),
                                 interpolation=cv2.INTER_AREA)
            teksten.append(lees(motor, img))
            hoeken.append(hoekstroken(motor, img))

        nieuw = dict(rec)
        if teksten:
            # langste is bijna altijd de achterkant
            teksten.sort(key=len, reverse=True)
            vol = "\n".join(teksten)
            hoektekst = "\n".join(hoeken)
            oud_n = len((rec.get("ocr_achterkant") or "").split())
            if len(teksten[0].split()) > oud_n:
                nieuw["ocr_achterkant"] = teksten[0][:4000]
                nieuw["ocr_voorkant"] = ("\n".join(teksten[1:]))[:800]
                nieuw["ocr_bron"] = "rapidocr"
                beter += 1
            nieuw["ocr_hoekstrook"] = hoektekst[:800]

            velden = uit_tekst(hoektekst + "\n" + vol)
            hoek_eerst = uit_tekst(hoektekst)["catno_kandidaten"]
            kand = hoek_eerst + [c for c in velden["catno_kandidaten"]
                                 if c not in hoek_eerst]
            if kand and not rec.get("catno_kandidaten"):
                nieuwe_nrs += 1
            if kand:
                nieuw["catno_kandidaten"] = kand
            for k in ("land", "jaar", "barcode"):
                if velden.get(k) and not rec.get(k):
                    nieuw[k] = velden[k]

        uit.append(nieuw)
        json.dump(uit, open(a.uitvoer, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        merk = "+nr" if (nieuw.get("catno_kandidaten") and not rec.get("catno_kandidaten")) else "   "
        print(f"[{i}/{len(platen)}] {rec['id']:<8} {merk} "
              f"{len((nieuw.get('ocr_achterkant') or '').split()):>5} woorden  "
              f"{(nieuw.get('catno_kandidaten') or ['-'])[0][:22]}")

    print(f"\n{a.uitvoer} geschreven in {int(time.time()-t0)}s.")
    print(f"  {beter} van {len(uit)} kregen meer tekst")
    print(f"  {nieuwe_nrs} kregen een catalogusnummer dat er eerst niet was")
    print(f"\nNu:  py automatch.py {a.uitvoer} platen.json --rest voor_claude.json")


if __name__ == "__main__":
    main()
