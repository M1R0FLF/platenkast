#!/usr/bin/env python3
"""
automatch.py - probeert elke plaat volledig lokaal te identificeren, zonder
dat er een model aan te pas komt.

Werkwijze per plaat uit ruw.json:
  1. zoek op elk catalogusnummer dat uit de OCR kwam
  2. haal de tracklist van elke kandidaat op
  3. tel hoeveel van die titels letterlijk in de OCR-tekst voorkomen

Die derde stap is de sleutel. Een catalogusnummer kan verkeerd gelezen zijn of
bij een andere plaat horen, maar als zes van de tien tracktitels terugkomen in
de tekst op de achterkant, dan is het de juiste persing. Dat is een hardere
verificatie dan wat een model op een foto kan zien.

Wat hij zeker weet gaat naar platen.json met bron "auto". De rest blijft over
voor Claude Code, en dat is meteen een veel kortere lijst.

    py automatch.py ruw.json platen.json
"""
import os, re, sys, json, time, argparse, difflib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lookup import Discogs, LAND


def norm(s):
    return re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())


def plat(s):
    return re.sub(r"\s+", " ", norm(s)).strip()


def kaal(s):
    """Alleen letters en cijfers, geen spaties.

    RapidOCR geeft de inhoud van één tekstvak aaneengeplakt terug:
    ALLINEEDISYOURSWEETLOVIN'2:47ASCAP. Een tracktitel als "All I Need Is Your
    Sweet Lovin'" is daar met spaties nooit in terug te vinden. Zes platen die
    met tesseract wél verifieerden vielen daardoor om. Zonder spaties
    vergelijken herstelt dat, zonder de eis zelf te verlagen: er moeten nog
    altijd evenveel tracktitels teruggevonden worden.
    """
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def bevat(hooiberg, naald):
    """Staat de titel in de tekst? Ruim, want OCR maakt fouten.
    `hooiberg` is al door kaal() gehaald."""
    naald = kaal(naald)
    if len(naald) < 6:
        return False
    if naald in hooiberg:
        return True
    # laat een paar tekens fout zijn
    venster = len(naald)
    for i in range(0, max(1, len(hooiberg) - venster), 4):
        if difflib.SequenceMatcher(None, naald, hooiberg[i:i + venster]).ratio() > 0.86:
            return True
    return False


def zoektermen(rec):
    """Bouw zoekopdrachten op artiest en titel uit de OCR.

    `koptekst` komt uit groepeer.py en bevat de grootst gedrukte regels van de
    voorkant, op grootte gesorteerd. Dat zijn vrijwel altijd de artiest en de
    titel. De oudere aanpak, de langste regels nemen, leverde eerder een adres
    of een copyrightregel op.
    """
    kand = []
    kop = [k for k in (rec.get("koptekst") or []) if len(k) >= 3][:4]
    for i in range(len(kop)):
        for j in range(i + 1, len(kop)):
            kand.append(f"{kop[i]} {kop[j]}")
    kand.extend(kop)
    for veld, aantal in (("ocr_voorkant", 3), ("ocr_achterkant", 2)):
        regels = [" ".join(l.split()) for l in (rec.get(veld) or "").splitlines()]
        regels = [l for l in regels
                  if len(re.sub(r"[^A-Za-z]", "", l)) >= 4 and len(l) <= 60]
        regels.sort(key=lambda l: -len(re.sub(r"[^A-Za-z]", "", l)))
        top = regels[:aantal]
        for i in range(len(top)):
            for j in range(i + 1, len(top)):
                kand.append(f"{top[i]} {top[j]}")
        kand.extend(top)
    uit, gezien = [], set()
    for k in kand:
        k = re.sub(r"[^\w &'-]", " ", k)
        k = re.sub(r"\s+", " ", k).strip()
        if 6 <= len(k) <= 70 and k.lower() not in gezien:
            gezien.add(k.lower())
            uit.append(k)
    return uit[:6]


def catno_varianten(cat):
    """Schrijfwijzen van hetzelfde catalogusnummer om op te zoeken.

    Discogs zoekt vrij letterlijk op catalogusnummer, en de OCR plakt de
    cijfergroepen aan elkaar of leest er eentje te veel. Gemeten:
    "68301690" gaf nul treffers, "6830 169" vond de plaat meteen.

    Levert hooguit een handvol varianten, want elke variant is een aanroep.
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

    # cijfergroepen die aaneengeplakt zijn weer uit elkaar halen
    for n in (cijfers, cijfers[:-1] if len(cijfers) >= 7 else ""):
        if len(n) == 7:
            erbij(f"{n[:4]} {n[4:]}")
            erbij(f"{n[:3]} {n[3:]}")
        elif len(n) == 6:
            erbij(f"{n[:3]} {n[3:]}")
    # letters los van de cijfers: WBSOUND5034 -> WB SOUND 5034
    if letters and cijfers and re.fullmatch(r"[A-Za-z]+\d+", cat.replace(" ", "")):
        erbij(f"{letters.group(1)} {cijfers}")
    return uit[:3]


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


def woordtermen(rec, aantal=6):
    """Losse, schone woorden uit de hele OCR, vaakst gezien eerst.

    Zoeken op het catalogusnummer alleen is soms niet genoeg: "17.335" gaf
    vijftig treffers van allerlei labels en de juiste stond er niet bij de
    eerste vier. Twee losse woorden van de plaat zelf, "ralph clouds", zetten
    hem meteen bovenaan. Woorden die op elke hoes staan vallen af.
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
    op_orde = sorted(telling.items(), key=lambda kv: (-kv[1], -len(kv[0])))
    return [w for w, _ in op_orde[:aantal]]


TRACKRUIS = re.compile(r"(?i)\b(side|kant|face|stereo|mono|records?|produced|"
                       r"arranged|publishing|music|made in|printed|copyright)\b")


def tracktermen(rec):
    """Regels van de achterkant die op een tracktitel lijken.

    Zoeken op artiest en titel strandt zodra de OCR daar een letter mist:
    "Bobby Vinton" kwam er als "Bobby linton" uit en dan vindt Discogs niets.
    Een tracklist heeft tien tot twintig titels, dus de kans dat er eentje
    schoon uit de OCR komt is veel groter. Discogs kent `track` als zoekveld.

    Alleen regels met een spatie: RapidOCR plakt de inhoud van een tekstvak
    aaneen, en juist de regels waar dat niet gebeurd is zijn de leesbare.
    """
    uit, gezien = [], set()
    for regel in (rec.get("ocr_achterkant") or "").splitlines():
        r = " ".join(regel.split())
        r = re.sub(r"\s*\d{1,2}[:'.]\d{2}.*$", "", r).strip()   # speelduur eraf
        # Volgnummer vooraan eraf: "9.THE MAN WHO SHOT LIBERTY VALANCE" vindt
        # niets, "THE MAN WHO SHOT LIBERTY VALANCE" vindt de plaat meteen.
        r = re.sub(r"^(?:[AB]?\d{1,2}\s*[.)\-]\s*|[AB]\s*[.)\-]\s*)", "", r).strip()
        if not (6 <= len(r) <= 40) or " " not in r:
            continue
        letters = re.sub(r"[^A-Za-z]", "", r)
        if len(letters) < 5 or len(letters) / len(r) < 0.65:
            continue
        if TRACKRUIS.search(r) or sum(1 for c in r if c.isupper()) == len(letters):
            pass                      # HOOFDLETTERS mag, ruiswoorden niet
        if TRACKRUIS.search(r):
            continue
        k = letters.lower()
        if k in gezien:
            continue
        gezien.add(k)
        uit.append(r)
    return uit[:5]


# Persingen die zelden de plaat in je hand zijn. Deze verzameling komt uit
# Belgie, dus een Keniaanse of Filipijnse persing is onwaarschijnlijk, en een
# release zonder label is meestal geen winkelexemplaar. Zonder deze rem koos
# automatch een DDR-persing "Not On Label" voor Tom Jones, op een hoes die
# gewoon DECCA zegt.
# Een lijst van verre landen bijhouden werkt niet: na Kenia en de Filipijnen
# kwam Libanon erbij. Andersom is het sluitend: dit zijn de landen waar een in
# Belgie gekochte plaat vandaan kan komen. Alles daarbuiten krijgt aftrek.
DICHTBIJ = {
    "belgium", "netherlands", "germany", "west germany", "france", "uk",
    "europe", "italy", "spain", "ireland", "switzerland", "austria", "denmark",
    "sweden", "norway", "finland", "portugal", "greece", "luxembourg",
    "france & benelux", "benelux", "scandinavia", "yugoslavia", "poland",
    "czechoslovakia", "hungary", "us", "usa", "canada", "uk & europe",
    "germany, austria, & switzerland", "uk & ireland", "netherlands, belgium",
}


def onwaarschijnlijk(land, labels):
    """Hoeveel punten aftrek verdient deze persing op voorhand?"""
    straf = 0.0
    l = (land or "").lower().strip()
    if l and l not in DICHTBIJ:
        straf += 2.0
    if "not on label" in " ".join(labels).lower():
        straf += 2.0
    return straf


def voorscore(cat, r, tekst, rec):
    """Rangschikt een zoekresultaat ZONDER de release op te halen.

    Hier zat de traagheid. Voor elke plaat werden de tracklists van tot
    vierentwintig kandidaten opgehaald, elk een aanroep van ruim een seconde,
    terwijl Discogs in het zoekresultaat zelf al titel, catalogusnummer, land
    en het aantal bezitters meestuurt. Daarmee is vooraf te zien welke
    kandidaten kansrijk zijn, zodat alleen die de dure ophaal waard zijn.
    """
    s = 0.0
    titel = r.get("title") or ""
    stukken = titel.split(" - ")
    if bevat(tekst, stukken[-1]):
        s += 2
    if len(stukken) > 1 and bevat(tekst, stukken[0]):
        s += 1
    cn = re.sub(r"[^a-z0-9]", "", (r.get("catno") or "").lower())
    if len(cn) >= 5 and cn in tekst:
        s += 2
    if not str(cat).startswith("tekstzoek"):
        s += 1
    s -= 0.6 * (r.get("_catrang") or 0)
    land = (rec.get("land") or "").lower().strip()
    rl = (r.get("country") or "").lower()
    if land and rl:
        s += 1 if (land in rl or rl in land) else -1
    have = (r.get("community") or {}).get("have") or 0
    s += min(have, 2000) / 2000.0
    labels = r.get("label") or []
    s -= onwaarschijnlijk(r.get("country"), labels if isinstance(labels, list) else [labels])
    return s


def soort_uit(rel, aantal_tracks):
    fmt = " ".join(d for f in (rel.get("formats") or [])
                   for d in ((f.get("descriptions") or []) + [f.get("name") or "",
                                                              f.get("text") or ""])).lower()
    if "maxi" in fmt:
        return "maxi12"
    if '7"' in fmt or "45 rpm" in fmt:
        return "single7"
    if "ep" in fmt.split():
        return "EP"
    return "LP" if aantal_tracks >= 5 else "single7"


def streng_genoeg(raak, aantal, bonus, min_treffers, min_deel, via_catno=False):
    """Is de verificatie gehaald?

    Let op: dit is GEEN versoepeling van de drempel. De oude regel eiste altijd
    minstens drie teruggevonden tracktitels. Een 7"-single heeft er twee, dus
    die kon per definitie nooit slagen, hoe goed de OCR ook was. Gemeten: van de
    24 automatisch herkende platen waren er 24 LP en 0 single, terwijl ruwweg de
    helft van de verzameling uit singles bestaat.

    Voor een korte tracklist is de eis daarom niet lager maar hoger: ALLE
    nummers moeten terugkomen (100% in plaats van 45%), en er moet bovendien
    bevestiging zijn uit de artiestennaam of het land.
    """
    if aantal >= 5:
        return raak >= min_treffers and raak / aantal >= min_deel
    if aantal >= 3:
        return raak >= 2 and raak / aantal >= 0.6

    # Een single heeft twee nummers. Eerst eiste ik ze allebei PLUS bevestiging
    # uit artiest of land. Gemeten op de overgebleven platen gooide dat goede
    # treffers weg: Mal D'amour, Masterpiece en Le Tombeur kwamen alle drie via
    # hun catalogusnummer binnen met de A-kant herkend, en vielen af omdat de
    # B-kant onleesbaar was en het land onbekend.
    #
    # Een gevonden catalogusnummer is op zichzelf al hard bewijs: dat nummer
    # staat op geen andere plaat. Samen met een teruggevonden tracktitel is dat
    # genoeg. Zonder catalogusnummer blijft de oude, strengere eis staan.
    if aantal < 1:
        return False
    if via_catno:
        return raak >= 1 and (raak == aantal or bonus >= 1)
    return raak == aantal and bonus >= 1


def probeer(dc, rec, min_treffers, min_deel):
    tekst = kaal(" ".join([rec.get("ocr_achterkant") or "",
                           rec.get("ocr_voorkant") or "",
                           rec.get("ocr_hoekstrook") or ""]))
    # Deze drempel stond op 120 tekens en gooide goede platen weg zonder ze
    # ook maar op te zoeken: "Je Ne Peux Vivre Sans Toi" heeft 99 tekens OCR en
    # bleek daarna een volledige 2-op-2 treffer. Twee plaatlabels leveren nu
    # eenmaal weinig tekst. De verificatie verderop is streng genoeg; deze
    # drempel hoeft alleen te voorkomen dat we zoeken met lege handen.
    if not tekst and not (rec.get("catno_kandidaten") or rec.get("barcode")
                          or rec.get("koptekst")):
        return None, "geen OCR-tekst om mee te zoeken"

    # De volgorde van catno_kandidaten is betekenisvol: groepeer.py zet de
    # vondsten uit de hoekstrook vooraan, en dat is het nummer van de plaat
    # zelf. Wat daarna komt staat vaak elders op de hoes, bijvoorbeeld in een
    # advertentie voor andere platen van hetzelfde label. Tom Jones werd zo
    # "Live! At The Talk Of The Town" (SLK16483, het tweede nummer) terwijl de
    # hoes "A-tom-ic Jones" (SLK16464, het eerste) is. Rang telt dus mee.
    kandidaten, gezocht = [], 0
    for rang, cat in enumerate((rec.get("catno_kandidaten") or [])[:5]):
        for v in catno_varianten(cat):
            if gezocht >= 8:                 # elke variant is een aanroep
                break
            gezocht += 1
            for r in dc.search(type="release", catno=v, format="Vinyl")[:4]:
                if all(r["id"] != x[1]["id"] for x in kandidaten):
                    r["_catrang"] = rang
                    kandidaten.append((v, r))
    if rec.get("barcode"):
        for r in dc.search(type="release", barcode=rec["barcode"], format="Vinyl")[:3]:
            kandidaten.append((rec["barcode"], r))
    # Ook zoeken op wat er op de hoes staat. Dit gebeurde vroeger alleen als
    # het catalogusnummer NIETS opleverde, maar een ruisnummer levert vaak wel
    # iets op, en dan werd er nooit op artiest en titel gezocht. De verificatie
    # op de tracklist blijft even streng, dus een misser wordt alsnog geweigerd.
    if len(kandidaten) < 8:
        # Land meegeven versmalt enorm. Zonder dat krijg je vijftig persingen
        # van hetzelfde album terug en staat de jouwe op plaats dertig.
        land = rec.get("land")
        for q in zoektermen(rec):
            varianten = ([{"q": q, "format": "Vinyl", "country": land}] if land else []) \
                        + [{"q": q, "format": "Vinyl"}]
            for kw in varianten:
                for r in dc.search(type="release", **kw)[:8]:
                    if all(r["id"] != x[1]["id"] for x in kandidaten):
                        kandidaten.append((f"tekstzoek: {q}", r))
            if len(kandidaten) >= 20:
                break
    # Nog steeds niets? Dan op de tracktitels zelf zoeken. Dat is het laatste
    # redmiddel als artiest en titel te slecht gelezen zijn om op te zoeken.
    # Zoeken op tracktitel klinkt sterk (het vindt Gene Pitney waar artiest en
    # titel falen) maar leverde gemeten over de hele restlijst nul extra platen
    # op, en kostte wel drie en een halve minuut. De treffers zijn meestal een
    # single met dat nummer, terwijl de plaat een verzamel-LP is. Daarom alleen
    # nog als er echt geen catalogusnummer is om op te zoeken.
    # Paren van losse woorden. Vangt de gevallen waar het catalogusnummer wel
    # gelezen is maar te veel treffers geeft om iets aan te hebben.
    if len(kandidaten) < 14:
        woorden = woordtermen(rec)
        for q in [f"{woorden[i]} {woorden[j]}"
                  for i in range(min(3, len(woorden)))
                  for j in range(i + 1, min(i + 3, len(woorden)))][:3]:
            for r in dc.search(type="release", q=q, format="Vinyl")[:6]:
                if all(r["id"] != x[1]["id"] for x in kandidaten):
                    kandidaten.append((f"tekstzoek: {q}", r))

    for t in ([] if rec.get("catno_kandidaten") else tracktermen(rec)[:3]):
        for r in dc.search(type="release", track=t, format="Vinyl")[:8]:
            if all(r["id"] != x[1]["id"] for x in kandidaten):
                kandidaten.append((f"tekstzoek: track {t}", r))
        if len(kandidaten) >= 26:
            break

    if not kandidaten:
        return None, "geen nummer en geen bruikbare zoekterm uit de OCR"

    # Eerst goedkoop rangschikken, dan pas de besten ophalen. Dat scheelt het
    # leeuwendeel van de aanroepen, en daarmee de wachttijd.
    kandidaten.sort(key=lambda p: -voorscore(p[0], p[1], tekst, rec))

    # Twaalf, niet acht: bij acht vielen zeven platen af die er met de volledige
    # lijst wel uitkwamen (Bobby Vinton, Lee Towers, Tino Rossi en nog wat).
    # Twaalf kost ongeveer een minuut extra over de hele set en haalt ze terug.
    beste = None
    for cat, r in kandidaten[:12]:
        rel = dc.release(r["id"])
        if not rel:
            continue
        titels = [t["title"] for t in (rel.get("tracklist") or []) if t.get("title")]
        if not titels:
            continue
        raak = sum(1 for t in titels if bevat(tekst, t))
        deel = raak / len(titels)

        # Bevestiging die los staat van de tracklist. Nodig omdat lang niet
        # elke achterkant een tracklist draagt: op "A-tom-ic Jones" staat een
        # verhaal over Tom Jones en geen enkel nummer, dus verifieren op
        # tracktitels kan daar per definitie niet slagen. De hoes noemt dan wel
        # de titel, het label en het catalogusnummer, en die drie samen wijzen
        # net zo hard een persing aan.
        rlabels = rel.get("labels") or []
        bev = 0
        if bevat(tekst, rel.get("title") or ""):
            bev += 2
        if any(bevat(tekst, l.get("name") or "") for l in rlabels):
            bev += 1
        rcatno = re.sub(r"[^a-z0-9]", "",
                        ((rlabels[0].get("catno") if rlabels else "") or "").lower())
        if len(rcatno) >= 5 and rcatno in tekst:
            bev += 2
        # Op een singlehoes staat vaak "from the album ..." met het
        # catalogusnummer van die LP erbij. Dan wordt de LP herkend in plaats
        # van de single, met de prijs van de verkeerde plaat als gevolg.
        # Twee plaatlabels leveren een paar honderd tekens, een LP-achterkant
        # met tracklist veel meer, dus de omvang van de OCR verraadt welke van
        # de twee het is.
        if len(tekst) < 400 and len(titels) >= 5:
            bev -= 3
        # Gevonden via het catalogusnummer van de hoes: Discogs koppelde dat
        # nummer zelf aan deze persing, en dat is bewijs op zichzelf.
        if not str(cat).startswith("tekstzoek"):
            bev += 1

        # Twee dingen die meetellen bij het KIEZEN tussen persingen, maar niet
        # als bewijs. Ze staan daarom los van bev, anders zou een populaire
        # plaat de acceptatiedrempel halen zonder dat er iets herkend is.
        #
        #  - rang van het catalogusnummer: het eerste komt uit de hoekstrook
        #    en is het nummer van de plaat zelf.
        #  - hoeveel mensen de persing bezitten: deze platen zijn in Belgie
        #    gekocht, dus een gangbare Europese persing is waarschijnlijker dan
        #    een zeldzame. Zonder dit koos automatch een Keniaanse ABBA, een
        #    Filipijnse Gerard Joling en een Canadese Diana Ross, terwijl de
        #    hoes "PRINTED IN HOLLAND" zei.
        have = (rel.get("community") or {}).get("have") or 0
        keuze = (bev - 0.6 * (r.get("_catrang") or 0) + min(have, 2000) / 2000.0
                 - onwaarschijnlijk(rel.get("country"),
                                    [l.get("name") or "" for l in rlabels]))
        # Een overduidelijke treffer hoeft niet tegen de rest afgewogen te
        # worden. Alle kandidaten nalopen kost twintig aanroepen van ruim een
        # seconde per plaat, en dat is waar de tijd in ging.
        zeker = (len(titels) >= 5 and deel >= 0.8 and raak >= 5)

        # artiest en titel als extra bevestiging
        art = plat(", ".join(a["name"] for a in (rel.get("artists") or [])))
        bonus = 0
        if art and len(art) > 3 and bevat(tekst, art.split(",")[0]):
            bonus += 1
        land = (rel.get("country") or "").lower()
        wl = LAND.get((rec.get("land") or "").lower(), (rec.get("land") or "").lower())
        if wl and land and (wl in land or land in wl):
            bonus += 1

        # Tellen alleen hoeveel titels raak zijn kiest bij een single de
        # verkeerde plaat: de verzamelaar "The Singles" haalde met 3 van 23
        # titels meer treffers dan de single "Under Attack" met 2 van 2, en won
        # daarmee. Het product raak*deel weegt aantal en aandeel tegen elkaar:
        # een LP met 10 van 12 (8,3) blijft ruim boven een toevallige 3 van 23
        # (0,4), en een volledige single (2,0) wint van diezelfde 3 van 23.
        punt = (round(raak * deel + keuze, 3), raak, bonus)
        if beste is None or punt > beste[0]:
            beste = (punt, rel, titels, cat, bev)
        if zeker and bonus >= 1:
            break

    if beste is None:
        return None, "geen bruikbare kandidaat"
    (_, raak, bonus), rel, titels, cat, bev = beste
    deel = raak / max(len(titels), 1)
    via_catno = not str(cat).startswith("tekstzoek")
    goed = streng_genoeg(raak, len(titels), bonus, min_treffers, min_deel, via_catno)
    # Tweede weg: titel plus label of catalogusnummer van de hoes teruggevonden,
    # met minstens een tracktitel als anker. Geen versoepeling maar een ander
    # soort bewijs, voor hoezen zonder tracklist op de achterkant.
    hoe = "tracklist"
    if not goed and bev >= 3 and raak >= 1:
        goed, hoe = True, "titel en label/catalogusnummer"
    # Zonder ook maar een tracktitel mag het alleen als het bewijs uit de
    # andere hoek compleet is: titel EN label EN het catalogusnummer, gevonden
    # via datzelfde nummer. Op een singlelabel staat de titel vaak over twee
    # tekstvakken verdeeld ("LADY / JOE / IN BLUE"), en dan is er geen enkele
    # tracktitel letterlijk terug te vinden terwijl de plaat wel vaststaat.
    elif not goed and bev >= 5 and via_catno:
        goed, hoe = True, "titel, label en catalogusnummer"
    if not goed:
        return None, f"verificatie te zwak ({raak}/{len(titels)} tracks herkend)"

    labels = rel.get("labels") or [{}]
    return {
        "id": rec["id"],
        "fotos": rec.get("fotos") or [],
        "artist": ", ".join(a["name"] for a in (rel.get("artists") or []))[:120] or None,
        "title": rel.get("title"),
        "label": labels[0].get("name"),
        "catno": labels[0].get("catno"),
        "barcode": rec.get("barcode"),
        "country": rel.get("country"),
        "year": rel.get("year") or rec.get("jaar"),
        "soort": soort_uit(rel, len(titels)),
        "lp_count": int((rel.get("formats") or [{}])[0].get("qty") or 1),
        "gatefold": "gatefold" in " ".join(
            (f.get("text") or "") for f in (rel.get("formats") or [])).lower(),
        "a_kant": None, "b_kant": None,
        "aantal_nummers": len(titels),
        "notes": f"automatisch herkend via {cat}, geverifieerd op {hoe}, "
                 f"{raak} van {len(titels)} tracktitels teruggevonden in de OCR",
        "staat_hoes": None,
        "bron": "auto",
        "release_id_auto": rel["id"],
    }, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("invoer", nargs="?", default="ruw.json")
    ap.add_argument("uitvoer", nargs="?", default="platen.json")
    ap.add_argument("--rest", default="voor_claude.json")
    ap.add_argument("--min-treffers", type=int, default=3,
                    help="minstens zoveel tracktitels moeten terugkomen in de OCR")
    ap.add_argument("--min-deel", type=float, default=0.45,
                    help="en minstens dit aandeel van de volledige tracklist")
    a = ap.parse_args()

    ruw = json.load(open(a.invoer, encoding="utf-8"))
    klaar = {}
    if os.path.exists(a.uitvoer):
        for r in json.load(open(a.uitvoer, encoding="utf-8")):
            klaar[str(r.get("id"))] = r

    dc = Discogs(os.environ.get("DISCOGS_TOKEN"))
    if not dc.token:
        print("Geen DISCOGS_TOKEN: dit gaat ruim twee keer trager.\n")

    rest, nieuw = [], 0
    t0 = time.time()
    for i, rec in enumerate(ruw, 1):
        # hartslag voor voortgang.py: elke plaat, ook de niet-herkende
        json.dump({"invoer": a.invoer, "gedaan": i - 1, "totaal": len(ruw),
                   "herkend": len(klaar), "start": t0},
                  open("automatch_voortgang.json", "w", encoding="utf-8"))
        rid = str(rec["id"])
        if rid in klaar:
            print(f"[{i}/{len(ruw)}] {rid}  al gedaan")
            continue
        res, reden = probeer(dc, rec, a.min_treffers, a.min_deel)
        if res:
            klaar[rid] = res
            nieuw += 1
            print(f"[{i}/{len(ruw)}] {rid}  AUTO  {res['artist']} - {res['title']} "
                  f"({res['country']} {res['year']})")
            json.dump(list(klaar.values()), open(a.uitvoer, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
        else:
            rest.append(rec)
            print(f"[{i}/{len(ruw)}] {rid}  voor Claude: {reden}")

    json.dump(list(klaar.values()), open(a.uitvoer, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(rest, open(a.rest, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    tot = len(ruw)
    print(f"\n{nieuw} nieuw automatisch herkend, {len(klaar)} in {a.uitvoer} totaal.")
    print(f"{len(rest)} van {tot} blijven over voor Claude Code -> {a.rest}")
    if tot:
        print(f"Dat is {100*(tot-len(rest))//tot}% dat geen enkel token kost.")


if __name__ == "__main__":
    main()
