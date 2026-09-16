#!/usr/bin/env python3
"""
beeldgelijk.py - vergelijkt een foto van een hoes met een hoesafbeelding van
Discogs, volledig lokaal.

Waarom dit er is
----------------
Wat na de tekstronde overblijft zijn hoezen waar de OCR te weinig van maakt:
donkere hoezen, en platen waarvan maar één foto bestaat zodat er geen tweede
kant is om een tracklist op te verifieren. Tekst helpt daar niet meer, maar de
hoes zelf is een plaatje, en Discogs heeft datzelfde plaatje.

ORB zoekt herkenningspunten in beide beelden en kijkt of die in hetzelfde
onderlinge verband staan. Dat overleeft het verschil tussen een scan en een
foto: andere belichting, wat perspectief, een rand eromheen.

Alles draait op de PC. Het enige netwerkverkeer is het ophalen van de
hoesafbeelding, en die worden bewaard in beeld_cache/.
"""
import os, re, hashlib
import cv2
import numpy as np
import requests

CACHE = "beeld_cache"
_sessie = None


def sessie():
    global _sessie
    if _sessie is None:
        _sessie = requests.Session()
        _sessie.headers["User-Agent"] = "VinylLister/2.0"
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
        r = sessie().get(url, timeout=25)
        if not r.ok:
            return None
        open(pad, "wb").write(r.content)
        arr = np.frombuffer(r.content, np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except Exception:
        return None


def klaarmaken(im, zijde=560):
    """Grijs, op maat, en contrast gelijkgetrokken zodat belichting minder
    uitmaakt."""
    if im is None:
        return None
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY) if im.ndim == 3 else im
    h, w = g.shape[:2]
    f = zijde / max(h, w)
    if f < 1:
        g = cv2.resize(g, (int(w * f), int(h * f)), interpolation=cv2.INTER_AREA)
    return cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(g)


_orb = None


def orb():
    global _orb
    if _orb is None:
        _orb = cv2.ORB_create(nfeatures=1500, scaleFactor=1.2, nlevels=8)
    return _orb


def kenmerken(im):
    g = klaarmaken(im)
    if g is None:
        return None, None
    kp, des = orb().detectAndCompute(g, None)
    return kp, des


def gelijkenis(kpA_desA, kpB_desB):
    """Geeft het aantal punten dat na een streng meetkundig filter overblijft.

    Alleen tellen hoeveel punten op elkaar lijken is niet genoeg: op twee
    willekeurige hoezen vind je zo ook tientallen toevalstreffers. Pas als die
    punten allemaal door dezelfde vervorming op elkaar passen (RANSAC op een
    homografie) gaat het echt om hetzelfde beeld.
    """
    kpA, desA = kpA_desA
    kpB, desB = kpB_desB
    if desA is None or desB is None or len(desA) < 10 or len(desB) < 10:
        return 0, 0
    bf = cv2.BFMatcher(cv2.NORM_HAMMING)
    try:
        paren = bf.knnMatch(desA, desB, k=2)
    except cv2.error:
        return 0, 0
    goed = [m for m, n in (p for p in paren if len(p) == 2) if m.distance < 0.75 * n.distance]
    if len(goed) < 8:
        return len(goed), 0
    src = np.float32([kpA[m.queryIdx].pt for m in goed]).reshape(-1, 1, 2)
    dst = np.float32([kpB[m.trainIdx].pt for m in goed]).reshape(-1, 1, 2)
    try:
        _, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
    except cv2.error:
        return len(goed), 0
    return len(goed), int(mask.sum()) if mask is not None else 0
