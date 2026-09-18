#!/usr/bin/env python3
"""
beeld.py - vergelijkt een foto van een hoes met de afbeelding op Discogs.

Gemeten op tien platen waarvan de persing al vaststond:

    juiste hoes    : 76 tot 766 samenvallende punten, mediaan 390
    verkeerde hoes : 0 tot 6

Geen grijs gebied maar een kloof. Een hoes die op vierhonderd punten
meetkundig samenvalt is hardere verificatie dan een tracklist, niet zachtere.

Alleen tellen hoeveel punten op elkaar lijken is niet genoeg: op twee
willekeurige hoezen vind je zo ook tientallen toevalstreffers. Pas als die
punten door dezelfde vervorming op elkaar passen (RANSAC op een homografie)
gaat het om hetzelfde beeld.
"""
import os, hashlib
import cv2
import numpy as np
import requests

CACHE = "cache/hoezen"
_sessie = None
_orb = None

# Leeg op de PC: daar gaat het rechtstreeks naar i.discogs.com. In de browser
# kan dat niet - i.discogs.com stuurt geen Access-Control-Allow-Origin, dus een
# fetch daarheen wordt geweigerd. Zet dit dan op een pad op je eigen herkomst
# dat doorstuurt (kast.py doet dat, en site/vercel.json ook). Zonder die omweg
# is er geen hoesbeeld en dus geen beeldronde, en juist die ving vijf van de 97
# platen af waar de tekst naar de verkeerde persing wees.
PROXY = ""
BRON = "https://i.discogs.com/"


def _via(url):
    if PROXY and url.startswith(BRON):
        return PROXY + url[len(BRON):]
    return url


def _ses():
    global _sessie
    if _sessie is None:
        _sessie = requests.Session()
        _sessie.headers["User-Agent"] = "VinylLister/3.0"
    return _sessie


def haal(url):
    """Hoesafbeelding ophalen, met schijfcache."""
    if not url:
        return None
    os.makedirs(CACHE, exist_ok=True)
    pad = os.path.join(CACHE, hashlib.md5(url.encode()).hexdigest() + ".jpg")
    if os.path.exists(pad):
        im = cv2.imread(pad)
        if im is not None:
            return im
    try:
        r = _ses().get(_via(url), timeout=25)
        if not r.ok:
            return None
        open(pad, "wb").write(r.content)
        return cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR)
    except Exception:
        return None


def _klaar(im, zijde=560):
    if im is None:
        return None
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY) if im.ndim == 3 else im
    h, w = g.shape[:2]
    f = zijde / max(h, w)
    if f < 1:
        g = cv2.resize(g, (int(w * f), int(h * f)), interpolation=cv2.INTER_AREA)
    return cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(g)


def kenmerken(im):
    global _orb
    if _orb is None:
        _orb = cv2.ORB_create(nfeatures=1500, scaleFactor=1.2, nlevels=8)
    g = _klaar(im)
    if g is None:
        return None, None
    return _orb.detectAndCompute(g, None)


def gelijkenis(a, b):
    """Aantal punten dat na het meetkundige filter overblijft."""
    kpA, desA = a
    kpB, desB = b
    if desA is None or desB is None or len(desA) < 10 or len(desB) < 10:
        return 0
    bf = cv2.BFMatcher(cv2.NORM_HAMMING)
    try:
        paren = bf.knnMatch(desA, desB, k=2)
    except cv2.error:
        return 0
    goed = [m for m, n in (p for p in paren if len(p) == 2)
            if m.distance < 0.75 * n.distance]
    if len(goed) < 8:
        return 0
    src = np.float32([kpA[m.queryIdx].pt for m in goed]).reshape(-1, 1, 2)
    dst = np.float32([kpB[m.trainIdx].pt for m in goed]).reshape(-1, 1, 2)
    try:
        _, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
    except cv2.error:
        return 0
    return int(mask.sum()) if mask is not None else 0
