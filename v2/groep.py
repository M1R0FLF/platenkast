#!/usr/bin/env python3
"""
groep.py - bepaalt welke foto's bij dezelfde plaat horen, STROMEND.

Waarom stromend
---------------
In v1 was dit een globale berekening over alle 225 foto's tegelijk: pas als
alles gelezen was kon er gegroepeerd worden, en pas daarna kon Discogs iets
opzoeken. Daardoor liepen rekenwerk en netwerk achter elkaar in plaats van
naast elkaar.

Miro fotografeert altijd voorkant, achterkant, en daarna eventueel de
binnenkant. Een plaat is dus af zodra de volgende voorkant begint: je hoeft
niet verder te kijken dan één foto vooruit. Daarmee kan een plaat naar Discogs
terwijl de rest nog gelezen wordt.

De signalen komen uit v1 en zijn daar gemeten op 28 paren binnen een plaat
tegenover 47 paren op een bekende plaatgrens:

    gedeeld catalogusnummer   5/28 binnen,  0/47 grenzen   <- nooit een misser
    trigramoverlap mediaan    0.75 binnen,  0.22 grens
    tijdgat mediaan           7s binnen,    16s grens

Twee harde regels doen de rest van het werk, en die komen van Miro zelf:
  - een plaat heeft minstens twee foto's (voorkant en achterkant)
  - een opengeklapte hoes (breder dan hoog) is altijd binnenwerk
"""
import re, datetime

RUIS = {"stereo", "mono", "records", "record", "side", "made", "printed", "rpm",
        "gema", "sabam", "biem", "bmi", "ascap", "music", "musique", "vocal",
        "produced", "arranged", "copyright", "manufactured", "tous", "droits",
        "long", "play", "microsillon", "originale", "prod"}

MAXGROOTTE = 4


def trigrammen(s):
    s = re.sub(r"[^a-z0-9]", "", (s or "").lower())
    return {s[i:i + 3] for i in range(len(s) - 2)}


def woorden(s):
    return {w for w in re.findall(r"[a-z0-9][a-z0-9.\-]{3,}", (s or "").lower())
            if w not in RUIS}


def nummers(s):
    """Catalogusnummer-achtige reeksen, punten weg zodat 45.VB.140.310 en
    45VB140310 hetzelfde opleveren."""
    uit = set()
    for m in re.findall(r"\d[\d.\-]{3,}", s or ""):
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


def kenmerk(res):
    """Maakt van een foto-uitslag (uit foto.verwerk) een groepeerbaar ding."""
    vol = (res.get("t") or "") + "\n" + (res.get("h") or "")
    return {
        **res,
        "tri": trigrammen(vol), "tok": woorden(vol), "cij": nummers(vol),
        "ts": stempel(res.get("naam") or ""),
        "n": len(re.sub(r"\s", "", res.get("t") or "")),
    }


def binding(a, b):
    """Hoe sterk hoort foto b bij foto a? Hoger is sterker."""
    s = 0.0
    if a["cij"] & b["cij"]:                 # hardste bewijs dat er is
        s += 3.0
    if len(a["tri"]) >= 25 and len(b["tri"]) >= 25:
        s += 3.0 * len(a["tri"] & b["tri"]) / min(len(a["tri"]), len(b["tri"]))
    s += 0.5 * min(len(a["tok"] & b["tok"]), 4)
    if a["ts"] and b["ts"]:
        g = int((b["ts"] - a["ts"]).total_seconds())
        s += (1.2 if g <= 8 else 0.7 if g <= 12 else 0.2 if g <= 20
              else -0.5 if g <= 40 else -1.5)
    return s


# Voorkeur voor de groepsgrootte. Een plaat met een foto bestaat niet (Miro
# fotografeert altijd voor- en achterkant), een paar is het normale geval, en
# meer moet zich bewijzen. Deze waarden komen uit v1, waar ze 100 platen
# opleverden en 21 van de 24 toen geverifieerde platen exact reproduceerden.
PRIOR = {1: -6.0, 2: 1.0, 3: -0.2, 4: -2.0}
NEUTRAAL = 1.0

# Hoeveel foto's er in de buffer moeten liggen voor er geknipt wordt, en
# hoeveel er aan het eind blijven liggen omdat ze nog kunnen aangroeien.
VENSTER, STAART = 16, 5


def segmenteer(rijen, prior=None, neutraal=NEUTRAAL, maxgrootte=MAXGROOTTE):
    """Knipt een reeks foto's optimaal op met dynamisch programmeren.

    Gulzig knippen kiest steeds het sterkste paar van dat moment en kan een
    betere knip verderop niet meer terugdraaien; gemeten haalde dat 87 van de
    100 platen gelijk aan deze aanpak. Hier wordt de som over de hele reeks
    gemaximaliseerd, zodat het vermoeden 'een plaat is een paar' en het
    tekstbewijs tegen elkaar afgewogen worden.
    """
    prior = prior or PRIOR
    n = len(rijen)
    if n == 0:
        return []
    band = [0.0] * (n + 1)
    for j in range(1, n):
        # een opengeklapte hoes is binnenwerk en hoort nooit bij een nieuwe
        # plaat: zonder deze regel werd de binnenkant van West Side Story een
        # losse plaat zonder tekst
        band[j] = 8.0 if rijen[j]["breed"] else binding(rijen[j - 1], rijen[j]) - neutraal

    NEG = float("-inf")
    best = [NEG] * (n + 1)
    vorig = [0] * (n + 1)
    best[0] = 0.0
    for b in range(1, n + 1):
        for L in range(1, min(maxgrootte, b) + 1):
            a = b - L
            if best[a] == NEG:
                continue
            s = best[a] + prior.get(L, -3.0) + sum(band[j] for j in range(a + 1, b))
            if s > best[b]:
                best[b], vorig[b] = s, a

    groepen, b = [], n
    while b > 0:
        a = vorig[b]
        groepen.append(list(range(a, b)))
        b = a
    groepen.reverse()
    return groepen


class Groepeerder:
    """Voer er foto's in op opnamevolgorde, haal er afgeronde platen uit.

    Draait dezelfde berekening als v1, maar over een schuivend venster in
    plaats van over de hele set. Zodra er genoeg foto's liggen wordt er
    geknipt, en alles behalve de staart gaat eruit. De staart blijft liggen
    omdat daar nog binnenwerk bij kan komen.
    """

    def __init__(self, venster=VENSTER, staart=STAART):
        self.venster, self.staart = venster, staart
        self.buffer = []

    def voeg_toe(self, foto):
        """Geeft een lijst afgeronde platen terug (meestal leeg)."""
        self.buffer.append(kenmerk(foto))
        if len(self.buffer) < self.venster:
            return []
        return self._knip(bewaar_staart=True)

    def rest(self):
        return self._knip(bewaar_staart=False)

    def _knip(self, bewaar_staart):
        if not self.buffer:
            return []
        groepen = segmenteer(self.buffer)
        if not bewaar_staart:
            uit = [[self.buffer[i] for i in g] for g in groepen]
            self.buffer = []
            return uit
        # alles vrijgeven wat ruim voor de staart eindigt
        grens = len(self.buffer) - self.staart
        klaar, rest_vanaf = [], 0
        for g in groepen:
            if g[-1] < grens:
                klaar.append([self.buffer[i] for i in g])
                rest_vanaf = g[-1] + 1
            else:
                break
        self.buffer = self.buffer[rest_vanaf:]
        return klaar


def maak_plaat(fotos):
    """Bouwt het plaatrecord uit de foto's van één plaat.

    De volgorde is betrouwbaarder dan de hoeveelheid tekst: de eerste foto is
    de voorkant, de tweede de achterkant, de rest binnenwerk. Juist op donkere
    hoezen zegt de hoeveelheid tekst niets meer en de volgorde nog alles.
    """
    from velden import uit_tekst

    voor, achter, binnen = fotos[0], (fotos[1] if len(fotos) > 1 else fotos[0]), fotos[2:]

    # Niet in de verleiding komen om dit op de hoeveelheid tekst te corrigeren.
    # Zes platen leken omgedraaid omdat hun voorkant meer woorden opleverde dan
    # hun achterkant, maar dat waren ze niet: op "Green, Green Grass Of Home"
    # staat de hele tracklist gewoon VOOROP, en bij een maxi-single staat achter
    # alleen een spiegelend logo. De volgorde waarin gefotografeerd is klopt,
    # de aanname dat een achterkant altijd het drukst is niet.
    t_achter = "\n".join(f["t"] or "" for f in [achter] + binnen).strip()
    t_voor = (voor["t"] or "").strip()
    hoek = "\n".join(f.get("h") or "" for f in fotos).strip()

    velden = uit_tekst(t_achter + "\n" + t_voor + "\n" + hoek)
    hoek_eerst = uit_tekst(hoek)["catno_kandidaten"]
    velden["catno_kandidaten"] = hoek_eerst + [c for c in velden["catno_kandidaten"]
                                               if c not in hoek_eerst]
    stam = re.sub(r"\D", "", fotos[0]["naam"])[-6:] or fotos[0]["naam"][:6]
    return {
        "id": stam,
        "fotos": [f["bestand"] for f in fotos],
        "ocr_achterkant": t_achter[:4000],
        "ocr_voorkant": t_voor[:800],
        "ocr_hoekstrook": hoek[:800],
        "koptekst": koptekst([voor]),
        **velden,
    }


KOPRUIS = re.compile(r"(?i)^(stereo|mono|long play|lp|ep|33|45|rpm|side|kant|face|"
                     r"records?|hi.?fi|digital|remaster\w*)\W*$")


def koptekst(fotos, aantal=6):
    """De grootst gedrukte regels van de voorkant: artiest en titel.

    RapidOCR geeft per tekstvak de hoogte terug, dus die volgorde is gratis.
    Veel beter dan 'de langste regel', want de langste regel op een hoes is
    meestal een adres of een copyrightregel.
    """
    vakken = []
    for f in fotos:
        for v in (f.get("vakken") or []):
            t = " ".join((v.get("t") or "").split())
            if len(re.sub(r"[^A-Za-z]", "", t)) < 3 or len(t) > 60 or KOPRUIS.match(t):
                continue
            vakken.append((float(v.get("h") or 0), t))
    vakken.sort(key=lambda x: -x[0])
    uit, gezien = [], set()
    for _, t in vakken:
        k = re.sub(r"[^a-z0-9]", "", t.lower())
        if k and k not in gezien:
            gezien.add(k)
            uit.append(t)
        if len(uit) >= aantal:
            break
    return uit
