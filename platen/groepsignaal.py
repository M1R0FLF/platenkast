#!/usr/bin/env python3
"""
groepsignaal.py - de signalen waarop foto's tot een plaat worden samengevoegd.

Apart gehouden van groepeer.py zodat de drempels los te meten zijn.

Waarom tekstgelijkenis en niet de hoeveelheid tekst
---------------------------------------------------
De verzameling bestaat uit LP's EN singles. Bij een LP is de achterkant een
tracklist met veel kleine tekst, en daar werkt "veel tekst = achterkant" nog.
Bij een 7" single zijn het twee PLAATLABELS: allebei twintig tot zestig tekens
in grote letters. Er is dan geen achterkant om op te ankeren.

Wat bij allebei wel geldt: twee foto's van dezelfde plaat delen tekst. Bij een
single staat op beide labels hetzelfde catalogusnummer (45.VB.140.310 /
45.VB.140.310, AA702A / AA702B, 101.109 / 101.109), bij een LP staat de titel
zowel voor als achter.

Gemeten op de 24 geverifieerde platen, 28 paren binnen een plaat tegen 47 paren
op een bekende plaatgrens:

    gedeeld catalogusnummer   5/28 binnen,  0/47 grenzen   <- geen enkele misser
    trigramoverlap mediaan    0.75 binnen,  0.22 grens
    tijdgat mediaan           7s binnen,    16s grens

Het catalogusnummer is dus het hardste bewijs, de trigramoverlap het breedste,
en het tijdgat de zwakste maar altijd aanwezige aanvulling.
"""
import os, re, json, datetime, statistics

RUIS = {"stereo", "mono", "records", "record", "side", "made", "printed", "rpm",
        "gema", "sabam", "biem", "bmi", "ascap", "music", "musique", "vocal",
        "produced", "arranged", "copyright", "manufactured", "tous", "droits",
        "long", "play", "microsillon", "originale", "made in", "prod"}


def trigrammen(s):
    s = re.sub(r"[^a-z0-9]", "", s.lower())
    return {s[i:i + 3] for i in range(len(s) - 2)}


def woorden(s):
    uit = set()
    for w in re.findall(r"[a-z0-9][a-z0-9.\-]{3,}", s.lower()):
        if w in RUIS:
            continue
        uit.add(w)
    return uit


def nummers(s):
    """Catalogusnummer-achtige reeksen. Punten en streepjes weggelaten zodat
    45.VB.140.310 en 45VB140310 hetzelfde opleveren."""
    uit = set()
    for m in re.findall(r"\d[\d.\-]{3,}", s):
        d = re.sub(r"\D", "", m)
        if len(d) >= 4:
            uit.add(d)
    return uit


def stempel(naam):
    d = re.sub(r"\D", "", naam)
    if len(d) < 14:
        return None
    try:
        return datetime.datetime.strptime(d[:14], "%Y%m%d%H%M%S")
    except ValueError:
        return None


def beeldverhouding(pad):
    """Breedte gedeeld door hoogte, zonder de hele foto te decoderen."""
    try:
        from PIL import Image
        with Image.open(pad) as im:
            w, h = im.size
        return w / h if h else 1.0
    except Exception:
        pass
    try:
        import cv2
        im = cv2.imread(pad)
        if im is None:
            return 1.0
        return im.shape[1] / im.shape[0]
    except Exception:
        return 1.0


def bouw_rijen(indir, cachepad):
    from leesfotos import sorteer
    cache = json.load(open(cachepad, encoding="utf-8"))
    rijen = []
    for f in sorteer(indir):
        naam = os.path.basename(f)
        c = cache.get(f"{naam}:{os.path.getsize(f)}") or {"t": "", "h": "", "vakken": []}
        t = (c.get("t") or "")
        h = (c.get("h") or "")
        vol = t + "\n" + h
        vak = c.get("vakken") or []
        hs = [v["h"] for v in vak] or [0.0]
        rijen.append({
            "pad": f, "naam": naam, "c": c,
            "n": len(re.sub(r"\s", "", t)),
            "vak": len(vak), "medh": statistics.median(hs),
            "tri": trigrammen(vol), "tok": woorden(vol), "cij": nummers(vol),
            "ts": stempel(naam),
            # Een opengeklapte hoes is twee panelen naast elkaar en dus veel
            # breder dan hoog. Zo'n foto is nooit een plaat op zichzelf.
            "breed": beeldverhouding(f) > 1.6,
        })
    for i, r in enumerate(rijen):
        v = rijen[i - 1]["ts"] if i else None
        r["gap"] = int((r["ts"] - v).total_seconds()) if (v and r["ts"]) else None
    return rijen


def samenvoeg_score(rijen, j):
    """Hoe sterk hoort foto j bij foto j-1? Hoger is sterker."""
    a, b = rijen[j - 1], rijen[j]
    s = 0.0

    # gedeeld catalogusnummer: hardste bewijs dat er is
    if a["cij"] & b["cij"]:
        s += 3.0

    # trigramoverlap, alleen als beide kanten genoeg tekst hebben. Bij een
    # vrijwel lege foto is de deling door de kleinste verzameling onzin.
    if len(a["tri"]) >= 25 and len(b["tri"]) >= 25:
        ov = len(a["tri"] & b["tri"]) / min(len(a["tri"]), len(b["tri"]))
        s += 3.0 * ov

    # gedeelde zeldzame woorden
    s += 0.5 * min(len(a["tok"] & b["tok"]), 4)

    # tijdgat: zwak maar altijd aanwezig
    g = b["gap"]
    if g is not None:
        s += (1.2 if g <= 8 else 0.7 if g <= 12 else 0.2 if g <= 20
              else -0.5 if g <= 40 else -1.5)
    return s


def voeg_samen(rijen, drempel, maxgrootte=4):
    """Begint met losse foto's en voegt steeds het sterkste buurpaar samen,
    zolang het boven de drempel zit en de groep niet te groot wordt.

    Achterhaald: gulzig samenvoegen kiest lokaal en loopt vast op ~14 van de 24
    geverifieerde platen. `segmenteer` doet hetzelfde globaal en haalt meer.
    Blijft staan omdat de meting ernaar verwijst."""
    n = len(rijen)
    groepen = [[i] for i in range(n)]
    scores = {j: samenvoeg_score(rijen, j) for j in range(1, n)}

    while True:
        beste, bestej = None, None
        for gi in range(len(groepen) - 1):
            j = groepen[gi + 1][0]              # naad tussen twee groepen
            if len(groepen[gi]) + len(groepen[gi + 1]) > maxgrootte:
                continue
            s = scores[j]
            if s >= drempel and (beste is None or s > beste):
                beste, bestej = s, gi
        if bestej is None:
            break
        groepen[bestej] = groepen[bestej] + groepen[bestej + 1]
        del groepen[bestej + 1]
    return groepen


# Een plaat is bijna altijd twee foto's: van de 24 geverifieerde platen waren er
# 20 een paar en 4 een drietal. Dat is een sterk voorafgaand vermoeden, en het
# hoort in de afweging thuis in plaats van in een drempel. Een enkeling of een
# viertal moet tekst-bewijs verdienen.
# Miro fotografeert ALTIJD voorkant, achterkant, en daarna eventueel de
# binnenkant. Een plaat met maar een foto bestaat dus niet: dat is altijd een
# verkeerde knip. Vandaar de zware aftrek op een eenling. Met -1.4 bleven er
# zes over, allemaal zonder tekst en zonder kans; vanaf -4 verdwijnen ze en
# blijft de rest van de indeling gelijk (100 groepen, 77 paren, 21 drietallen,
# 2 viertallen).
PRIOR = {1: -6.0, 2: 1.0, 3: -0.2, 4: -2.0}
NEUTRAAL = 1.0


def segmenteer(rijen, prior=None, neutraal=NEUTRAAL, maxgrootte=4):
    """Knipt de hele reeks in één keer optimaal op, met dynamisch programmeren.

    Gulzig samenvoegen kiest steeds het sterkste paar van dat moment en kan een
    goede knip verderop niet meer terugdraaien. Hier wordt de som over de hele
    reeks gemaximaliseerd, zodat het vermoeden 'een plaat is een paar' en het
    tekstbewijs tegen elkaar afgewogen worden.
    """
    prior = prior or PRIOR
    n = len(rijen)
    if n == 0:
        return []
    binding = [0.0] * (n + 1)
    for j in range(1, n):
        binding[j] = samenvoeg_score(rijen, j) - neutraal
        # Een opengeklapte hoes hoort altijd bij de plaat ervoor. Zonder deze
        # regel werden het losse "platen" zonder tekst waar niets mee te
        # beginnen viel: de binnenkant van West Side Story stond apart van de
        # hoes zelf. Van de 225 foto's zijn er 17 zo'n binnenkant.
        if rijen[j].get("breed"):
            binding[j] = 8.0

    NEG = float("-inf")
    best = [NEG] * (n + 1)
    vorig = [0] * (n + 1)
    best[0] = 0.0
    for b in range(1, n + 1):
        for L in range(1, min(maxgrootte, b) + 1):
            a = b - L
            if best[a] == NEG:
                continue
            s = best[a] + prior.get(L, -3.0) + sum(binding[j] for j in range(a + 1, b))
            if s > best[b]:
                best[b] = s
                vorig[b] = a

    groepen, b = [], n
    while b > 0:
        a = vorig[b]
        groepen.append(list(range(a, b)))
        b = a
    groepen.reverse()
    return groepen
