#!/usr/bin/env python3
"""
velden.py - haalt catalogusnummer, land, jaar en streepjescode uit OCR-tekst.

Alles hier is gemeten op de echte set van 225 foto's. De patronen zien er
willekeurig uit maar elk stukje vangt een fout die zich voordeed.
"""
import re

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
      | [A-Z][ .\-]?\d{5,6}                            # S 63151, S70044
                                                       # (een letter mag, maar
                                                       # dan minstens vijf
                                                       # cijfers: anders is
                                                       # "A1966" ineens een
                                                       # bestelnummer)
      | \d{2,3}[ ]\d{3}[ ]?-?[ ]?\d(?:[ ]?[A-Z]{1,3}\d?)?   # 415 253-1 GH2
      | \d?[ ]?[A-Z]\d{3}-\d{4,6}                       # 4 C058-90264
      | \d{2}\.[A-Z]{2}\.\d{3}\.\d{3}                   # 45.VB.140.310
      | \d{2,3}\.\d{3}\b                                # 101.109
      | \b\d{5,8}\b                                     # 212001, 2315321
    )(?=[AB]?\b)""")

# Een kantletter hoort bij de KANT, niet bij de plaat: op het label van de
# Anthony Quinn-single staat AA702A op de ene kant en AA702B op de andere, en
# het nummer van de plaat is AA702. Zonder dit vond het patroon helemaal niets
# - het struikelde over die letter - en bleef de plaat op de handmatige lijst
# staan terwijl hij gewoon op Discogs stond.
KANTLETTER = re.compile(r"^([A-Z]{1,6}[ .\-]?\d{3,6})[AB]$")

# Nummers uit een muziekcatalogus zijn geen bestelnummers. BWV1068 is het
# Bach-Werke-Verzeichnis, KV een Köchelnummer. Ze staan op elke klassieke hoes
# en leverden zoekopdrachten op die nooit iets konden vinden.
WERKNUMMER = re.compile(r"(?i)^(BWV|KV|K|HOB|WOO|OP|RV|D|BUXWV|TWV|HWV)[ .\-]?\d")

# RapidOCR plakt alles binnen een tekstvak aaneen: STEREO2315321. Het nummer
# zit dan midden in een woord en geen patroon met \b ervoor vindt het nog.
PLAKKERS = re.compile(r"(?i)\b(stereo|mono|face|side|kant|rpm|nr|no)[ .\-]?(?=\d)")

RUIS = {"STEREO", "MONO", "SIDE", "RECORDS", "RECORD", "PRINTED", "MADE",
        "MANUFACTURED", "RPM", "BMI", "ASCAP", "GEMA", "SABAM", "LTD",
        "LIMITED", "COPYRIGHT", "PRODUCED", "ARRANGED"}

WOORDRUIS = {
    "stereo", "mono", "records", "record", "side", "face", "kant", "made",
    "printed", "produced", "arranged", "publishing", "music", "musique",
    "vocal", "instrumental", "copyright", "manufactured", "distributed",
    "productions", "production", "recording", "recorded", "album", "long",
    "play", "limited", "company", "gmbh", "rpm", "the", "and", "for", "with",
    "from", "his", "her", "all", "you", "your", "this", "that", "includes",
    "including", "available", "also", "cassette", "photo", "cover", "design",
    "disque", "disques", "edition", "tous", "droits", "reserves", "tours",
    "haute", "fidelite", "orchestre", "direction", "musicassette",
}


def ontplak(t):
    return PLAKKERS.sub(r"\1 ", t or "")


def land_gedrukt(t):
    """Het land dat de hoes EXPLICIET noemt: "PRINTED IN HOLLAND", "MADE IN
    FRANCE". Dat is geen aanwijzing maar een mededeling, en dus veel harder dan
    het land dat ergens los in de tekst voorkomt (een liedtitel met "France"
    erin telt niet)."""
    laag = (ontplak(t) or "").lower()
    for k, n in LANDEN:
        if re.search(r"(printed|made|manufactured|pressed|imprime|fabrique)"
                     r"[^.\n]{0,40}" + re.escape(k), laag):
            return n
    return None


def uit_tekst(t):
    t = ontplak(t)
    laag = t.lower()
    land = land_gedrukt(t) or next(
        (n for k, n in LANDEN if re.search(r"\b" + re.escape(k) + r"\b", laag)), None)

    jaren = [int(y) for y in re.findall(r"\b(19[4-9]\d)\b", t)]
    jaar = max(set(jaren), key=jaren.count) if jaren else None

    bc = re.search(r"\b(\d{12,13})\b", re.sub(r"[ \-]", "", t))

    kand, gezien = [], set()
    for m in CATNO.finditer(t):
        v = " ".join(m.group(1).split())
        if v.upper() in RUIS or WERKNUMMER.match(v):
            continue
        k = KANTLETTER.match(v.upper())
        if k:
            v = k.group(1)
        if v.upper() not in gezien:
            gezien.add(v.upper())
            kand.append(v)
    return {"land": land, "land_gedrukt": land_gedrukt(t), "jaar": jaar,
            "barcode": bc.group(1) if bc else None,
            "catno_kandidaten": kand[:6]}


def catno_varianten(cat):
    """Schrijfwijzen van hetzelfde nummer om op te zoeken.

    Gemeten: "68301690" gaf nul treffers, "6830 169" vond de plaat meteen. De
    OCR plakt cijfergroepen aaneen of leest er een te veel.
    """
    cat = " ".join((cat or "").split())
    if not cat:
        return []
    uit = [cat]
    cijfers = re.sub(r"\D", "", cat)
    letters = re.match(r"^([A-Za-z]{1,6})", cat)

    def erbij(v):
        v = " ".join(v.split())
        if v and v not in uit:
            uit.append(v)

    for n in (cijfers, cijfers[:-1] if len(cijfers) >= 7 else ""):
        if len(n) == 7:
            erbij(f"{n[:4]} {n[4:]}")
            erbij(f"{n[:3]} {n[3:]}")
        elif len(n) == 6:
            erbij(f"{n[:3]} {n[3:]}")
    if letters and cijfers and re.fullmatch(r"[A-Za-z]+\d+", cat.replace(" ", "")):
        erbij(f"{letters.group(1)} {cijfers}")
    return uit[:3]


def woordtermen(rec, aantal=6):
    """Losse schone woorden uit alle OCR, vaakst gezien eerst.

    Discogs vindt "WHYDOFOOLSFALLIN LOVE" niet maar zet op "ROSS WHY" de juiste
    plaat op plek een. Aaneengeplakte tekst is waardeloos als zoekterm, losse
    woorden niet.
    """
    tekst = " ".join([rec.get("ocr_voorkant") or "", rec.get("ocr_achterkant") or "",
                      rec.get("ocr_hoekstrook") or "",
                      " ".join(rec.get("koptekst") or [])])
    telling = {}
    for w in re.findall(r"[A-Za-z]{3,14}", tekst):
        k = w.lower()
        if k in WOORDRUIS:
            continue
        telling[k] = telling.get(k, 0) + 1
    return [w for w, _ in sorted(telling.items(),
                                 key=lambda kv: (-kv[1], -len(kv[0])))[:aantal]]


TRACKRUIS = re.compile(r"(?i)\b(side|kant|face|stereo|mono|records?|produced|"
                       r"arranged|publishing|music|made in|printed|copyright)\b")


def tracktermen(rec, aantal=5):
    """Regels die op een tracktitel lijken. Alleen regels met een spatie: waar
    RapidOCR niet geplakt heeft is het leesbaar.

    Ook de voorkant, niet alleen de achterkant. Bij een verzamelaar staan de
    nummers vaak juist voorop - op Streisands Greatest Hits vult de tracklist de
    hele voorkant en staat achterop alleen een advertentie voor de rest van het
    fonds. Zolang alleen de achterkant gelezen werd, was er voor zo'n plaat geen
    enkele tracktitel om mee te zoeken.
    """
    kanten = []
    for kant in ("ocr_achterkant", "ocr_voorkant"):
        kanten.append(_tracklijnen(rec.get(kant) or ""))
    # Om en om, niet eerst alles van de achterkant. Anders vult een advertentie
    # achterop de hele lijst - bij Streisand leverde dat "FUNNY GIRL", "My Name
    # Is Barbra" en "Color Me Barbra" op, drie andere platen, terwijl de echte
    # tracklist voorop stond en nooit aan de beurt kwam.
    uit, gezien = [], set()
    for paar in zip(*[k + [None] * (max(map(len, kanten)) - len(k)) for k in kanten]):
        for r in paar:
            if r is None:
                continue
            k = re.sub(r"[^A-Za-z]", "", r).lower()
            if k not in gezien:
                gezien.add(k)
                uit.append(r)
    return uit[:aantal]


def _tracklijnen(blok):
    uit, gezien = [], set()
    for regel in blok.splitlines():
        r = " ".join(regel.split())
        r = re.sub(r"\s*\d{1,2}[:'.]\d{2}.*$", "", r).strip()
        r = re.sub(r"^(?:[AB]?\d{1,2}\s*[.)\-]\s*|[AB]\s*[.)\-]\s*)", "", r).strip()
        if not (6 <= len(r) <= 40) or " " not in r or TRACKRUIS.search(r):
            continue
        letters = re.sub(r"[^A-Za-z]", "", r)
        if len(letters) < 5 or len(letters) / len(r) < 0.65:
            continue
        k = letters.lower()
        if k not in gezien:
            gezien.add(k)
            uit.append(r)
    return uit


def kaal(s):
    """Alleen letters en cijfers. RapidOCR plakt woorden binnen een tekstvak
    aaneen, dus vergelijken gebeurt zonder spaties."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())
