#!/usr/bin/env python3
"""
contactvel.py - alle hoezen op een vel, om ze in een oogopslag te bekijken.

    py contactvel.py              een tegel per PLAAT, met artiest en prijs
    py contactvel.py --alles      elke uitgesneden foto, om het snijden te keuren

De eerste is om te zien wat je te koop hebt, de tweede om te zien of het
uitsnijden en rechtzetten gelukt is. Dat zijn twee verschillende vragen en
daarom twee vellen: op een vel per plaat zie je alleen de voorkant, en een
scheve achterkant blijft daar onzichtbaar.
"""
import os, csv, glob, argparse
import cv2
import numpy as np

TEGEL, KOL = 300, 6
GRIJS = (38, 38, 38)


def _plaats(vel, im, x, y, hoog):
    h, w = im.shape[:2]
    f = min((TEGEL - 8) / w, hoog / h)
    im = cv2.resize(im, (max(1, int(w * f)), max(1, int(h * f))),
                    interpolation=cv2.INTER_AREA)
    y0 = y + (hoog - im.shape[0]) // 2
    x0 = x + (TEGEL - im.shape[1]) // 2
    vel[y0:y0 + im.shape[0], x0:x0 + im.shape[1]] = im


def _tekst(vel, s, x, y, kleur=(235, 235, 235), schaal=.40):
    cv2.putText(vel, s[:34], (x + 4, y), cv2.FONT_HERSHEY_SIMPLEX, schaal,
                kleur, 1, cv2.LINE_AA)


def per_plaat(hoezendir, csvpad, uit):
    with open(csvpad, encoding="utf-8-sig", newline="") as fh:
        rijen = list(csv.DictReader(fh))
    rijen.sort(key=lambda r: ((r.get("artiest_discogs") or r.get("gelezen_artist") or "").lower(),
                              (r.get("titel_discogs") or r.get("gelezen_title") or "").lower()))
    n = len(rijen)
    rij_h = TEGEL + 34
    vel = np.full((((n + KOL - 1) // KOL) * rij_h, KOL * TEGEL, 3), GRIJS, np.uint8)

    for i, r in enumerate(rijen):
        fotos = [f for f in (r.get("fotos") or "").split(";") if f.strip()]
        im = None
        for f in fotos[:1]:                    # de voorkant is de eerste foto
            im = cv2.imread(os.path.join(hoezendir, os.path.basename(f)))
        rr, cc = divmod(i, KOL)
        x, y = cc * TEGEL, rr * rij_h
        if im is not None:
            _plaats(vel, im, x, y, TEGEL - 8)
        art = (r.get("artiest_discogs") or r.get("gelezen_artist") or "?")
        tit = (r.get("titel_discogs") or r.get("gelezen_title") or "?")
        prijs = (r.get("vraagprijs") or "").strip()
        _tekst(vel, art, x, y + TEGEL + 2)
        _tekst(vel, tit, x, y + TEGEL + 16, (170, 200, 170), .36)
        if prijs:
            cv2.putText(vel, f"EUR {prijs}", (x + TEGEL - 66, y + TEGEL + 2),
                        cv2.FONT_HERSHEY_SIMPLEX, .40, (120, 220, 255), 1, cv2.LINE_AA)
    cv2.imwrite(uit, vel, [cv2.IMWRITE_JPEG_QUALITY, 86])
    print(f"{n} platen -> {uit}  ({vel.shape[1]}x{vel.shape[0]})")


def alle_fotos(hoezendir, uit):
    paden = sorted(glob.glob(os.path.join(hoezendir, "*.jpg")))
    rij_h = TEGEL + 18
    vel = np.full((((len(paden) + KOL - 1) // KOL) * rij_h, KOL * TEGEL, 3),
                  GRIJS, np.uint8)
    for i, p in enumerate(paden):
        im = cv2.imread(p)
        if im is None:
            continue
        rr, cc = divmod(i, KOL)
        x, y = cc * TEGEL, rr * rij_h
        _plaats(vel, im, x, y, TEGEL - 8)
        _tekst(vel, os.path.basename(p)[3:17], x, y + TEGEL + 10, schaal=.36)
    cv2.imwrite(uit, vel, [cv2.IMWRITE_JPEG_QUALITY, 84])
    print(f"{len(paden)} foto's -> {uit}  ({vel.shape[1]}x{vel.shape[0]})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hoezen", default="hoezen")
    ap.add_argument("--csv", default="uit/platen.csv")
    ap.add_argument("--uit", default="")
    ap.add_argument("--alles", action="store_true",
                    help="elke uitgesneden foto in plaats van een per plaat")
    a = ap.parse_args()
    if a.alles:
        alle_fotos(a.hoezen, a.uit or "uit/contactvel-fotos.jpg")
    else:
        per_plaat(a.hoezen, a.csv, a.uit or "uit/contactvel-platen.jpg")


if __name__ == "__main__":
    main()
