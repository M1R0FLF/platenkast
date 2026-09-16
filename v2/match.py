#!/usr/bin/env python3
"""
match.py - zoekt de juiste persing op Discogs en verifieert die.

In v1 waren dit drie scripts die je na elkaar met de hand draaide
(automatch, herlees, beeldmatch). Hier is het een reeks strategieen die elk
hun eigen soort bewijs leveren, in volgorde van goedkoop naar duur:

  1. tracklist   - genoeg tracktitels van de persing komen terug in de OCR
  2. bevestiging - titel EN label/catalogusnummer van de hoes komen terug
  3. hoesbeeld   - de foto valt meetkundig samen met de afbeelding op Discogs

Alle drie zijn HARDE verificatie. De derde is zelfs de hardste: gemeten haalde
de juiste hoes 76 tot 766 samenvallende punten en de verkeerde hoogstens 6.

Wat er NIET gebeurt is een gok invullen. Blijft alles onder de maat, dan komt
de plaat op de handmatige lijst. Een verkeerde persing levert een verkeerde
prijs en dat merkt niemand nog.
"""
import os, re, difflib, collections
import cv2

from velden import (kaal, catno_varianten, woordtermen, tracktermen,
                    ontplak_woorden, WOORDRUIS)
import beeld

# Persingen die zelden de plaat in je hand zijn. Een lijst van verre landen
# bijhouden werkt niet: na Kenia en de Filipijnen kwam Libanon erbij. Andersom
# is het sluitend, dit zijn de landen waar een in Belgie gekochte plaat vandaan
# kan komen.
DICHTBIJ = {
    "belgium", "netherlands", "germany", "west germany", "france", "uk",
    "europe", "italy", "spain", "ireland", "switzerland", "austria", "denmark",
    "sweden", "norway", "finland", "portugal", "greece", "luxembourg",
    "france & benelux", "benelux", "scandinavia", "yugoslavia", "poland",
    "czechoslovakia", "hungary", "us", "usa", "canada", "uk & europe",
    "germany, austria, & switzerland", "uk & ireland", "netherlands, belgium",
}


def onwaarschijnlijk(land, labels):
    straf = 0.0
    if (land or "").lower().strip() and (land or "").lower().strip() not in DICHTBIJ:
        straf += 2.0
    if "not on label" in " ".join(labels or []).lower():
        straf += 2.0
    return straf


def bevat(hooiberg, naald):
    """Staat de titel in de tekst? `hooiberg` is al door kaal() gehaald.

    Zonder spaties vergelijken, want RapidOCR plakt de inhoud van een tekstvak
    aaneen: ALLINEEDISYOURSWEETLOVIN. In v1 vielen zes geverifieerde platen om
    toen dat nog met spaties gebeurde.
    """
    naald = kaal(naald)
    if len(naald) < 6:
        return False
    if naald in hooiberg:
        return True
    venster = len(naald)
    for i in range(0, max(1, len(hooiberg) - venster), 4):
        if difflib.SequenceMatcher(None, naald, hooiberg[i:i + venster]).ratio() > 0.86:
            return True
    return False


def streng_genoeg(raak, aantal, bonus, via_catno, min_treffers=3, min_deel=0.45):
    """Is de verificatie gehaald?

    Let op de korte tracklist. De oude regel eiste altijd drie teruggevonden
    titels, en een 7"-single heeft er twee: die kon dus nooit slagen, hoe goed
    de OCR ook was. Gemeten: van de eerste 24 automatisch herkende platen waren
    er 24 LP en 0 single, terwijl de helft van de verzameling single is.

    Voor een korte tracklist is de eis daarom niet lager maar hoger: alles moet
    kloppen, of anders het catalogusnummer als anker.
    """
    if aantal >= 5:
        return raak >= min_treffers and raak / aantal >= min_deel
    if aantal >= 3:
        return raak >= 2 and raak / aantal >= 0.6
    if aantal < 1:
        return False
    if via_catno:
        return raak >= 1 and (raak == aantal or bonus >= 1)
    return raak == aantal and bonus >= 1


# --------------------------------------------------------------- kandidaten --

def _zelfde_plaat_ander_land(dc, rec, tekst, beste, gedrukt, minstens=0.55):
    """Dezelfde plaat, maar dan de persing uit het land dat op de hoes staat.

    Wordt alleen aangeroepen als de tracklist de plaat al heeft aangewezen en
    het land van die persing de hoes tegenspreekt. De vraag is dan niet meer
    WELKE plaat het is - dat staat vast - maar welke persing, en daar is een
    gerichte zoekopdracht voor: artiest en titel van de winnaar, met het land
    erbij.

    De vervanger moet zich wel op eigen kracht bewijzen. Alleen "het land klopt"
    is geen bewijs: dan zou elke willekeurige Nederlandse plaat een Nederlandse
    hoes kunnen kapen. Daarom moet hij minstens `minstens` van het aandeel
    tracktitels halen dat de oorspronkelijke winnaar haalde.
    """
    rel = beste[1]
    titel = rel.get("title") or ""
    artiest = ", ".join(a["name"] for a in (rel.get("artists") or []))
    if not titel or not artiest:
        return None
    oud_deel = (beste[7] / len(beste[2])) if beste[2] else 0.0

    try:
        treffers = dc.zoek(artist=artiest.split(",")[0], release_title=titel,
                           country=gedrukt, format="Vinyl") or []
    except Exception:
        return None

    beter = None
    for r in treffers[:6]:
        rl = (r.get("country") or "").lower()
        if not (gedrukt in rl or rl in gedrukt):
            continue
        nieuw = dc.release(r["id"])
        if not nieuw:
            continue
        titels = [t["title"] for t in (nieuw.get("tracklist") or []) if t.get("title")]
        if not titels:
            continue
        raak = sum(1 for t in titels if bevat(tekst, t))
        deel = raak / len(titels)
        if deel < minstens * max(oud_deel, 0.01):
            continue
        have = (nieuw.get("community") or {}).get("have") or 0
        punt = (round(raak * deel + min(have, 2000) / 2000.0, 3), raak, 0)
        kandidaat = (punt, nieuw, titels, "landzoek", beste[4], beste[5], beste[6], raak)
        if beter is None or punt > beter[0]:
            beter = kandidaat
    return beter


def _zoektermen(rec):
    """Zoekopdrachten uit de grootst gedrukte regels van de voorkant."""
    kop = [k for k in (rec.get("koptekst") or []) if len(k) >= 3][:4]
    kand = [f"{kop[i]} {kop[j]}" for i in range(len(kop))
            for j in range(i + 1, len(kop))] + kop
    uit, gezien = [], set()
    for k in kand:
        k = re.sub(r"\s+", " ", re.sub(r"[^\w &'-]", " ", k)).strip()
        if 6 <= len(k) <= 70 and k.lower() not in gezien:
            gezien.add(k.lower())
            uit.append(k)
    return uit[:6]


def kandidaten(dc, rec, breed=False, hint=None):
    """Verzamelt mogelijke persingen. `breed` voor de beeldronde, waar ruis mag
    omdat de hoes toch beslist."""
    uit, gezien, gezocht = [], set(), 0

    def erbij(res, hoe):
        for r in res:
            if r["id"] not in gezien:
                gezien.add(r["id"])
                uit.append((hoe, r))

    if hint:
        kw = {"format": "Vinyl"}
        if hint.get("artist"):
            kw["artist"] = hint["artist"]
        if hint.get("title"):
            kw["release_title"] = hint["title"]
        if len(kw) > 1:
            erbij(dc.zoek(**kw)[:10], "hint artiest+titel")
        if hint.get("catno"):
            erbij(dc.zoek(catno=hint["catno"], format="Vinyl")[:8], "hint catno")

    # De volgorde van catno_kandidaten is betekenisvol: het eerste komt uit de
    # hoekstrook en is het nummer van de plaat zelf. Wat daarna komt staat vaak
    # in een advertentie voor andere platen van hetzelfde label.
    for rang, cat in enumerate((rec.get("catno_kandidaten") or [])[:5]):
        for v in catno_varianten(cat):
            if gezocht >= 8:
                break
            gezocht += 1
            for r in dc.zoek(catno=v, format="Vinyl")[:6 if breed else 4]:
                if r["id"] not in gezien:
                    r["_catrang"] = rang
                    gezien.add(r["id"])
                    uit.append((v, r))
    if rec.get("barcode"):
        erbij(dc.zoek(barcode=rec["barcode"], format="Vinyl")[:3], "barcode")

    for q in _zoektermen(rec)[:3]:
        erbij(dc.zoek(q=q, format="Vinyl")[:8], f"tekstzoek: {q}")

    # Losse schone woorden. Dit is wat het bij aaneengeplakte OCR wel doet:
    # "ROSS WHY" zet de juiste plaat op plek een waar de volledige geplakte
    # titel niets oplevert.
    if breed or len(uit) < 14:
        w = woordtermen(rec)
        paren = [f"{w[i]} {w[j]}" for i in range(min(3, len(w)))
                 for j in range(i + 1, min(i + 3, len(w)))]
        for q in (paren + w[:2] if breed else paren[:3]):
            erbij(dc.zoek(q=q, format="Vinyl")[:12 if breed else 6], f"tekstzoek: {q}")
            if len(uit) >= (40 if breed else 24):
                break

    # Zoeken op tracktitel, altijd. Dit is het sterkste dat een achterkant te
    # bieden heeft: artiest en titel staan er vaak verminkt op ("linton" voor
    # Vinton, "ATOM-C" voor A-tom-ic) en op een verzamelplaat staat de artiest
    # helemaal niet groot, maar de tracklist is lang en daar komt er altijd wel
    # een schoon uit.
    #
    # Het echte werk zit in de DOORSNEDE: een plaat die twee van onze
    # tracktitels bevat is vrijwel zeker de juiste. Een enkele tracktitel is
    # dat niet, want "A Little Bit More" staat op honderd platen.
    # Alleen de doorsnede telt. Een plaat die maar op EEN tracktitel gevonden
    # is, is ruis: "A Little Bit More" staat op honderd platen, en zo werd
    # Pablito Y Sus Trovadores Paraguayos een keer "Cobla Barcelona - La
    # Sardana". Vanaf twee gedeelde titels is het vrijwel zeker de juiste.
    tel, gevonden = {}, {}
    for t in tracktermen(rec, 6)[:4]:
        for r in dc.zoek(track=t, format="Vinyl")[:10]:
            tel[r["id"]] = tel.get(r["id"], 0) + 1
            gevonden.setdefault(r["id"], (f"tekstzoek: {t}", r))
    for rid, n in tel.items():
        if n < 2 or rid in gezien:
            continue
        hoe, r = gevonden[rid]
        r["_tracks"] = n
        gezien.add(rid)
        uit.append((hoe, r))
    for _, r in uit:
        if r["id"] in tel and tel[r["id"]] >= 2:
            r["_tracks"] = tel[r["id"]]
    return uit


def voorscore(cat, r, tekst, rec):
    """Rangschikt een zoekresultaat ZONDER de release op te halen.

    Hier zat de traagheid in v1: voor elke plaat werden tot vierentwintig
    tracklists opgehaald, elk een aanroep van ruim een seconde, terwijl Discogs
    in het zoekresultaat zelf al titel, catalogusnummer, land en het aantal
    bezitters meestuurt.
    """
    s = 0.0
    stukken = (r.get("title") or "").split(" - ")
    if bevat(tekst, stukken[-1]):
        s += 2
    if len(stukken) > 1 and bevat(tekst, stukken[0]):
        s += 1
    cn = kaal(r.get("catno"))
    if len(cn) >= 5 and cn in tekst:
        s += 2
    if not str(cat).startswith(("tekstzoek", "hint", "barcode")):
        s += 1
    s -= 0.6 * (r.get("_catrang") or 0)
    # gevonden via meerdere tracktitels tegelijk: dat is bijna bewijs op zich
    s += 3.0 * max(0, (r.get("_tracks") or 0) - 1)
    land = (rec.get("land") or "").lower().strip()
    rl = (r.get("country") or "").lower()
    if land and rl:
        s += 1 if (land in rl or rl in land) else -1
    # een op de hoes GEDRUKT land weegt zwaarder dan een losse landnaam
    gedrukt = (rec.get("land_gedrukt") or "").lower().strip()
    if gedrukt and rl:
        s += 2 if (gedrukt in rl or rl in gedrukt) else -4
    s += min((r.get("community") or {}).get("have") or 0, 2000) / 2000.0
    lab = r.get("label")
    return s - onwaarschijnlijk(r.get("country"), lab if isinstance(lab, list) else [])


# ---------------------------------------------------------------- strategie --

def is_verzamel(rec):
    """Ziet de hoes eruit als een verzamelplaat?

    Een verzamel-LP zet artiestennamen op de voorkant, gescheiden door
    streepjes: "Leo Sayer-Billy Preston and Syreeta-Randy Crawford-Rod Stewart".
    De tracklist van zo'n plaat bevat de nummers van al die artiesten, en dan
    slaagt de verificatie ook op de losse single van een van hen: "Woman In
    Love" werd zo "Dr. Hook - A Little Bit More", een van de nummers erop.
    """
    voor = (rec.get("ocr_voorkant") or "") + " " + " ".join(rec.get("koptekst") or [])
    streepjes = len(re.findall(r"[A-Za-z]{3,}\s*[-·]\s*[A-Z][a-z]{2,}", voor))
    merk = bool(re.search(r"(?i)\bTV[\s.\-]?\d?[\s.\-]?LP\b|dubbel ?album|"
                          r"\b20 (greatest|golden|great)\b", voor))
    return streepjes >= 3 or merk


def _tekst_van(rec):
    return kaal(" ".join([rec.get("ocr_achterkant") or "", rec.get("ocr_voorkant") or "",
                          rec.get("ocr_hoekstrook") or ""]))


def op_tekst(dc, rec, hint=None):
    """Strategie 1 en 2: tracklist, of titel plus label/catalogusnummer."""
    tekst = _tekst_van(rec)
    voortekst = kaal(rec.get("ocr_voorkant") or "")
    # genoeg woorden op de voorkant om het ontbreken van de titel iets te laten
    # betekenen; bij een hoes die alleen uit een foto bestaat zegt het niets
    voor_bruikbaar = len(re.findall(r"[A-Za-z]{3,}",
                                    rec.get("ocr_voorkant") or "")) >= 4
    # Een fondslijst herken je aan de vorm: een plaat heeft EEN nummer, een
    # advertentie voor de rest van het fonds een rij van dezelfde soort.
    # Streisands achterkant leverde er negen op, allemaal met een S ervoor.
    kandnrs = [kaal(c) for c in (rec.get("catno_kandidaten") or []) if len(kaal(c)) >= 4]
    _vaakst = collections.Counter(c[0] for c in kandnrs).most_common(1)
    fondslijst = len(kandnrs) >= 4 and bool(_vaakst) and _vaakst[0][1] >= 4
    if not tekst and not (rec.get("catno_kandidaten") or rec.get("koptekst")):
        return None, "geen OCR-tekst om mee te zoeken"
    kand = kandidaten(dc, rec, hint=hint)
    if not kand:
        return None, "geen kandidaat op Discogs"

    kand.sort(key=lambda p: -voorscore(p[0], p[1], tekst, rec))
    verzamel = is_verzamel(rec)
    beste, bekeken = None, []
    for cat, r in kand[:12]:
        rel = dc.release(r["id"])
        if not rel:
            continue
        titels = [t["title"] for t in (rel.get("tracklist") or []) if t.get("title")]
        if not titels:
            continue
        raak = sum(1 for t in titels if bevat(tekst, t))
        deel = raak / len(titels)

        rlabels = rel.get("labels") or []
        bev = 0
        titel_voor = bool(voortekst) and bevat(voortekst, rel.get("title") or "")
        if bevat(tekst, rel.get("title") or ""):
            bev += 2
            # WAAR de titel staat telt mee. Op de achterkant van een plaat staat
            # vaak een advertentie voor de rest van het fonds: bij Streisands
            # Greatest Hits een raster met zes andere albums, compleet met hun
            # catalogusnummers. Titel en nummer van zo'n advertentie kloppen
            # allebei perfect met de OCR, en dan wint een plaat die hier niet
            # eens in de hoes zit - "Je M'appelle Barbra" in plaats van de
            # Greatest Hits waar de voorkant vol mee staat.
            #
            # De voorkant is wel van deze plaat. Staat de titel daarop, dan is
            # dat het sterkste bewijs dat er is; staat hij ALLEEN achterop
            # terwijl de voorkant leesbaar is, dan is dat een aanwijzing dat het
            # om zo'n advertentie gaat.
            if titel_voor:
                bev += 2
            elif voor_bruikbaar:
                bev -= 3
        if any(bevat(tekst, l.get("name") or "") for l in rlabels):
            bev += 1
        rcatno = kaal((rlabels[0].get("catno") if rlabels else "") or "")
        if len(rcatno) >= 5 and rcatno in tekst:
            # Een nummer uit de fondslijst achterop is geen bewijs. Het staat er
            # wel, maar het hoort bij een andere plaat, en het klopt even
            # perfect als het echte nummer. Streisands Greatest Hits kwam zo uit
            # op "Je M'appelle Barbra": de titel was door de OCR vermalen tot
            # "Je mappelle Barbm" en telde niet mee, maar S62776 stond er
            # gewoon, dus won die plaat op het nummer alleen.
            #
            # Bij een fondslijst moet de titel dus ook echt op de VOORKANT
            # staan. Doet hij dat niet, dan zegt het nummer niets.
            bev += 0 if (fondslijst and not titel_voor) else 2
        # Het nummer op de hoes IS het nummer van de plaat. Staat het nummer van
        # deze persing er niet op terwijl de hoes wel een nummer laat zien, dan
        # is het de verkeerde persing - of zelfs een andere plaat.
        #
        # Gemeten op 21 gevallen waar v1 en v2 een andere persing kozen: in 5
        # daarvan stond alleen het nummer van v1 op de hoes en in 0 alleen dat
        # van v2. Zonder deze rem werd "Le Disque D'Or de Charles Aznavour"
        # (2C 064-16 055) het buurnummer van Gilbert Becaud (2C 064-16.050), en
        # werd een verzamel-LP de single van Dr. Hook die erop staat.
        cijfers_hoes = re.sub(r"\D", "", tekst)
        if rec.get("catno_kandidaten") and len(rcatno) >= 5:
            if re.sub(r"\D", "", rcatno) not in cijfers_hoes:
                bev -= 3
        # Op een singlehoes staat vaak "from the album ..." met het nummer van
        # die LP erbij. Dan wordt de LP herkend in plaats van de single, met de
        # prijs van de verkeerde plaat als gevolg. Twee plaatlabels leveren een
        # paar honderd tekens, een LP-achterkant met tracklist veel meer.
        if len(tekst) < 400 and len(titels) >= 5:
            bev -= 3
        via_catno = not str(cat).startswith(("tekstzoek", "hint", "barcode"))
        if via_catno:
            bev += 1

        art = ", ".join(a["name"] for a in (rel.get("artists") or []))
        # Een verzamelhoes hoort bij een verzamelplaat, niet bij de single van
        # een van de artiesten die erop staan.
        if verzamel:
            bev += 2 if art.strip().lower().startswith("various") else -3
        bonus = 0
        if art and len(art) > 3 and bevat(tekst, art.split(",")[0]):
            bonus += 1
        land = (rec.get("land") or "").lower()
        rl = (rel.get("country") or "").lower()
        if land and rl and (land in rl or rl in land):
            bonus += 1

        # Staat er "PRINTED IN HOLLAND" op de hoes, dan is het een Nederlandse
        # persing. Punt. Dat werd eerder even zwaar gewogen als een landnaam die
        # toevallig ergens in de tekst stond, en daardoor kwamen er zeven platen
        # op een Britse, Amerikaanse of Spaanse persing terecht terwijl de hoes
        # zelf Holland zei. Het land bepaalt de prijs, dus dat mag niet.
        gedrukt = (rec.get("land_gedrukt") or "").lower()
        if gedrukt and rl:
            klopt = gedrukt in rl or rl in gedrukt
            bev += 2 if klopt else -6

        have = (rel.get("community") or {}).get("have") or 0
        keuze = (bev - 0.6 * (r.get("_catrang") or 0) + min(have, 2000) / 2000.0
                 - onwaarschijnlijk(rel.get("country"),
                                    [l.get("name") or "" for l in rlabels]))
        # Tellen alleen hoeveel titels raak zijn kiest bij een single de
        # verkeerde plaat: "The Singles" haalde met 3 van 23 meer treffers dan
        # "Under Attack" met 2 van 2. Het product weegt aantal en aandeel.
        punt = (round(raak * deel + keuze, 3), raak, bonus)
        bekeken.append((punt, rel, titels, cat, bev, via_catno, bonus, raak))
        if beste is None or punt > beste[0]:
            beste = bekeken[-1]

    if beste is None:
        return None, "geen bruikbare kandidaat"
    # Staat er een land op de hoes gedrukt en spreekt de winnaar dat tegen, kijk
    # dan of er tussen de bekeken kandidaten DEZELFDE plaat zit met het juiste
    # land. Dat is niet dezelfde plaat goedkoper maken maar de juiste persing
    # kiezen: het land bepaalt de prijs.
    gedrukt = (rec.get("land_gedrukt") or "").lower().strip()
    if gedrukt and beste is not None:
        def rijmt(rl):
            rl = (rl or "").lower()
            return bool(rl) and (gedrukt in rl or rl in gedrukt or "europe" in rl)

        if not rijmt(beste[1].get("country")):
            titel_w = kaal(beste[1].get("title") or "")[:18]
            zelfde = [b for b in bekeken
                      if rijmt(b[1].get("country"))
                      and kaal(b[1].get("title") or "")[:18] == titel_w]
            if zelfde:
                beste = max(zelfde, key=lambda b: b[0])
            else:
                # Niets uit het juiste land TUSSEN DE KANDIDATEN - maar dat zegt
                # alleen iets over de zoekopdracht, niet over Discogs. De
                # tracklist heeft inmiddels bewezen WELKE plaat dit is; alleen
                # de persing klopt niet. Dus nog een keer zoeken, nu gericht op
                # het land dat op de hoes staat.
                #
                # Dit haalde twee platen terug die anders met de hand hadden
                # gemoeten: de Nederlandse persing van Streisands Greatest Hits
                # en de Duitse van het Chopin-verzamelalbum. Bij allebei stond
                # de plaat gewoon op Discogs, maar kwam hij niet boven met een
                # zoekopdracht op catalogusnummer - die nummers stonden in de
                # advertentie op de achterkant en hoorden bij andere platen.
                vervang = _zelfde_plaat_ander_land(dc, rec, tekst, beste, gedrukt)
                if vervang is not None:
                    beste = vervang
                else:
                    # Echt niets uit het juiste land. Dan is dit de verkeerde
                    # persing en dus de verkeerde prijs. Liever niets invullen:
                    # op de handmatige lijst valt het op, in de CSV niet.
                    return None, (f"hoes zegt {rec.get('land_gedrukt')}, maar de beste "
                                  f"kandidaat is {beste[1].get('country')}")

    _, rel, titels, cat, bev, via_catno, bonus, raak = beste

    # Een verzamelhoes die uitkomt op de single van een van de artiesten erop
    # is fout, en fout is erger dan niets: dan hangt er een verkeerde prijs aan.
    # "Woman In Love" werd zo "Dr. Hook - A Little Bit More". Liever met de
    # hand, want de juiste plaat stond niet eens tussen de kandidaten: de OCR
    # las de titel als "CWomum" en daar vindt Discogs niets op.
    art_rel = ", ".join(a["name"] for a in (rel.get("artists") or [])).strip().lower()
    if verzamel and not art_rel.startswith("various") and len(titels) < 8:
        return None, ("hoes lijkt een verzamelplaat, maar de beste kandidaat is "
                      f"een plaat van {art_rel[:28] or 'een artiest'} erop")

    if streng_genoeg(raak, len(titels), bonus, via_catno):
        return _plaat(rec, rel, titels, f"{raak} van {len(titels)} tracktitels "
                      f"teruggevonden (via {cat})", "tracklist"), None
    if bev >= 3 and raak >= 1:
        return _plaat(rec, rel, titels, f"titel en label/catalogusnummer "
                      f"teruggevonden (via {cat})", "bevestiging"), None
    if bev >= 5 and via_catno:
        return _plaat(rec, rel, titels, f"titel, label en catalogusnummer "
                      f"teruggevonden (via {cat})", "bevestiging"), None
    return None, f"verificatie te zwak ({raak}/{len(titels)} tracks herkend)"


def op_beeld(dc, rec, hoezendir, drempel=30, hint=None):
    """Strategie 3: de hoes zelf vergelijken met de afbeelding op Discogs."""
    eigen = []
    for naam in (rec.get("fotos") or []):
        im = cv2.imread(os.path.join(hoezendir, naam))
        if im is not None:
            eigen.append(beeld.kenmerken(im))
    if not eigen:
        return None, "geen leesbare foto"
    kand = kandidaten(dc, rec, breed=True, hint=hint)
    if not kand:
        return None, "geen kandidaat op Discogs"

    # Dezelfde hoes zit op elke persing van een plaat, dus het beeld wijst de
    # PLAAT aan maar niet de persing. Daarvoor is het catalogusnummer nodig:
    # zonder deze weging koos de beeldronde voor "La Tendresse" een Franse
    # heruitgave (90 070) terwijl op de hoes 80486 staat.
    tekst = _tekst_van(rec)
    cijfers_hoes = re.sub(r"\D", "", tekst)

    scores = []
    for hoe, r in kand[:30]:
        hoes = beeld.haal(r.get("cover_image") or r.get("thumb"))
        if hoes is None:
            continue
        kh = beeld.kenmerken(hoes)
        best = max((beeld.gelijkenis(kf, kh) for kf in eigen), default=0)
        lab = r.get("label")
        straf = 3 * onwaarschijnlijk(r.get("country"),
                                     lab if isinstance(lab, list) else [])
        rc = re.sub(r"\D", "", kaal(r.get("catno")))
        if len(rc) >= 4 and cijfers_hoes:
            straf += -25 if rc in cijfers_hoes else 12
        gedrukt = (rec.get("land_gedrukt") or "").lower().strip()
        rl = (r.get("country") or "").lower()
        if gedrukt and rl and not (gedrukt in rl or rl in gedrukt):
            straf += 20      # de hoes noemt zelf een ander land
        scores.append((best - straf, best, hoe, r))
    if not scores:
        return None, "geen hoesafbeeldingen gevonden"
    scores.sort(key=lambda s: -s[0])

    # Niets gevonden? Dan is onze foto misschien de achterkant. Van sommige
    # platen bestaat maar een foto en dat is soms de achterkant; Discogs
    # bewaart die er meestal bij.
    if scores[0][1] < drempel:
        for _, _, hoe, r in scores[:4]:
            rel = dc.release(r["id"]) or {}
            for i in (rel.get("images") or [])[1:4]:
                hoes = beeld.haal(i.get("uri"))
                if hoes is None:
                    continue
                kh = beeld.kenmerken(hoes)
                best = max((beeld.gelijkenis(kf, kh) for kf in eigen), default=0)
                if best >= drempel:
                    scores.append((best, best, hoe + " (achterkant)", r))
        scores.sort(key=lambda s: -s[0])

    top = scores[0]
    if top[1] < drempel:
        return None, f"beeld komt niet overeen (beste {top[1]} punten)"

    # Dezelfde hoes zit op elke persing, dus als de hoes een land noemt en de
    # gevonden persing komt ergens anders vandaan, is het de verkeerde. Eerst
    # kijken of dezelfde plaat ook uit het juiste land bestaat.
    gedrukt = (rec.get("land_gedrukt") or "").lower().strip()
    if gedrukt:
        def rijmt(rl):
            rl = (rl or "").lower()
            return bool(rl) and (gedrukt in rl or rl in gedrukt or "europe" in rl)

        if not rijmt(top[3].get("country")):
            goed = [s for s in scores if s[1] >= drempel and rijmt(s[3].get("country"))]
            if goed:
                top = goed[0]
            else:
                return None, (f"hoes zegt {rec.get('land_gedrukt')}, maar de "
                              f"gevonden persing is {top[3].get('country')}")

    rel = dc.release(top[3]["id"])
    if not rel:
        return None, "release niet op te halen"
    titels = [t["title"] for t in (rel.get("tracklist") or []) if t.get("title")]
    plaat = _plaat(rec, rel, titels,
                   f"{top[1]} samenvallende punten met de afbeelding op Discogs "
                   f"(gevonden via {top[2]})", "hoesbeeld")
    plaat["beeld_punten"] = top[1]      # ook hier vastleggen, niet alleen in de tekst
    return plaat, None


# Uit beeld.py, en opnieuw bevestigd over alle 97 herkende platen: de 92 juiste
# haalden 35 tot 766 punten, de 5 foute hoogstens 8. Geen enkele plaat kwam
# ertussen uit. Daarom mag onder de tien "tegenspraak" heten.
BEELD_FOUT, BEELD_GOED = 10, 30


def kan_hoes_zijn(afbeelding):
    """Kan dit plaatje een hoes zijn, of is het een foto van het LABEL?

    Een platenhoes is ongeveer vierkant. Op de Belgische Decca-persing van Tom
    Jones staan alleen twee liggende foto's van 600x400 - het plaatje zelf, niet
    de hoes. Die vergelijken met een hoesfoto levert vijf punten op, en dat lijkt
    op tegenspraak terwijl het gewoon een ander onderwerp is.

    Bij een onbekend formaat niets uitsluiten: liever een keer voor niets
    vergelijken dan een echte hoes overslaan.
    """
    if not (afbeelding.get("uri") or afbeelding.get("resource_url")):
        return False
    b, h = afbeelding.get("width") or 0, afbeelding.get("height") or 0
    return True if not (b and h) else 0.75 <= b / h <= 1.4


def beeld_punten(dc, rec, release_id, hoezendir, eigen=None):
    """Hoeveel punten valt onze eigen foto samen met DEZE release?

    Dit is de enige toets in de hele keten die niet uit de OCR komt, en daarmee
    de enige die een achterkant vol reclame kan tegenspreken. Op de ABBA-single
    "Under Attack" staat "Extrait du double album 30cm <<The Singles>> - 406506":
    titel en catalogusnummer van een andere plaat, vlak bij elkaar, precies waar
    de tekststrategie op afgaat. Alleen de hoes zelf weet beter.

    Geeft None als er niets te vergelijken viel; dat is geen tegenspraak.
    """
    if eigen is None:
        eigen = []
        for naam in (rec.get("fotos") or [])[:2]:
            im = cv2.imread(os.path.join(hoezendir, os.path.basename(naam)))
            if im is not None:
                eigen.append(beeld.kenmerken(im))
    if not eigen or not release_id:
        return None
    rel = dc.release(release_id) or {}
    urls = [i.get("uri") or i.get("resource_url")
            for i in (rel.get("images") or [])[:4] if kan_hoes_zijn(i)]
    if not urls:
        return None          # geen hoes om mee te vergelijken; geen tegenspraak
    top = None
    for u in [x for x in urls if x]:
        hoes = beeld.haal(u)
        if hoes is None:
            continue
        kh = beeld.kenmerken(hoes)
        punten = max((beeld.gelijkenis(kf, kh) for kf in eigen), default=0)
        top = punten if top is None else max(top, punten)
        if top >= BEELD_GOED:
            break                      # verder kijken verandert het oordeel niet
    return top


def _ankers(rec, n=3):
    """De grootst gedrukte woorden van de voorkant: artiest of componist."""
    uit, gezien = [], set()
    for regel in (rec.get("koptekst") or []):
        for w in re.findall(r"[A-Za-z][A-Za-z'\-]{3,}", ontplak_woorden(regel)):
            k = w.lower()
            if k not in WOORDRUIS and k not in gezien:
                gezien.add(k)
                uit.append(w)
    return uit[:n]


def _onderscheidend(rec, n=6):
    """Lange hoofdletterwoorden van de achterkant.

    Niet de VAAKSTE woorden, met opzet. Op een klassieke hoes zijn dat de
    sponsor, de stad en de gezongen tekst; wat de plaat identificeert - het
    ensemble, de titel van het werk - staat er vaak maar een keer. Een eigennaam
    begint met een hoofdletter en is meestal lang, en dat is hier een veel beter
    signaal dan hoe vaak iets voorkomt.
    """
    tekst = ontplak_woorden(rec.get("ocr_achterkant") or "")
    uit, gezien = [], set()
    for w in re.findall(r"\b[A-Z][a-zA-Z'\-]{5,}", tekst):
        k = w.lower()
        if k not in WOORDRUIS and k not in gezien:
            gezien.add(k)
            uit.append(w)
    return uit[:n]


def laatste_ronde(dc, rec, hoezendir, drempel=None, max_zoek=16):
    """Breed zoeken met korte zoekopdrachten, en alleen het beeld mag tekenen.

    Draait alleen voor platen die anders op de handmatige lijst belanden, dus
    de kosten zijn beperkt tot de paar procent die overblijft.

    Twee woorden per zoekopdracht, niet zes: Discogs EN-t de termen, dus elk
    extra woord is een kans dat er NUL treffers terugkomen - en nul treffers is
    erger dan ruis, want dan is er niets meer voor de hoes om uit te kiezen.

    De winnende combinatie is niet altijd "artiest + iets". Voor de
    Bach-plaat was het "Magnificat Ouverture": twee WERKtitels, zonder de
    componist. Daarom ook de onderscheidende woorden onderling gepaard.

    Dit mag zo breed zoeken omdat accepteren alleen op het beeld kan. Een
    scattergun levert geen fout antwoord op als de hoes moet tekenen.
    """
    drempel = BEELD_GOED if drempel is None else drempel
    eigen = []
    for naam in (rec.get("fotos") or [])[:2]:
        im = cv2.imread(os.path.join(hoezendir, os.path.basename(naam)))
        if im is not None:
            eigen.append(beeld.kenmerken(im))
    if not eigen:
        return None, "geen leesbare foto"

    ank, ond = _ankers(rec), _onderscheidend(rec)
    vragen = [f"{a} {w}" for a in ank[:2] for w in ond[:5]]
    vragen += [f"{ond[i]} {ond[j]}" for i in range(min(4, len(ond)))
               for j in range(i + 1, min(4, len(ond)))]

    top, gezien = (0, None, None), set()
    for q in vragen[:max_zoek]:
        for r in dc.zoek(q=q, format="Vinyl")[:8]:
            if r["id"] in gezien:
                continue
            gezien.add(r["id"])
            hoes = beeld.haal(r.get("cover_image") or r.get("thumb"))
            if hoes is None:
                continue
            punten = max((beeld.gelijkenis(kf, beeld.kenmerken(hoes))
                          for kf in eigen), default=0)
            if punten > top[0]:
                top = (punten, r, q)
        if top[0] >= drempel:
            break                      # gevonden is gevonden, stop met zoeken
    if top[0] < drempel:
        return None, f"ook breed zoeken leverde niets op (beste {top[0]} punten)"

    rel = dc.release(top[1]["id"])
    if not rel:
        return None, "release niet op te halen"
    titels = [t["title"] for t in (rel.get("tracklist") or []) if t.get("title")]
    plaat = _plaat(rec, rel, titels,
                   f"{top[0]} samenvallende punten met de afbeelding op Discogs "
                   f"(breed gezocht via '{top[2]}')", "hoesbeeld")
    plaat["beeld_punten"] = top[0]
    return plaat, None


def _plaat(rec, rel, titels, waarom, hoe):
    labels = rel.get("labels") or [{}]
    fmt = " ".join(d for f in (rel.get("formats") or [])
                   for d in ((f.get("descriptions") or []) + [f.get("name") or "",
                                                              f.get("text") or ""])).lower()
    # Het aantal nummers is pas de laatste redding, niet het eerste bewijs: de
    # Bach-plaat is een gewone LP met twee werken erop (Ouverture en Magnificat)
    # en werd zo een single7, met de prijsbodem van een single. Zegt Discogs
    # zelf "LP" of "Album", dan is dat het antwoord.
    woorden = fmt.split()
    soort = ("maxi12" if "maxi" in fmt else
             "single7" if ('7"' in fmt or "45 rpm" in fmt) else
             "EP" if "ep" in woorden else
             "LP" if ("lp" in woorden or "album" in fmt or len(titels) >= 5)
             else "single7")
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
        "soort": soort,
        "lp_count": int((rel.get("formats") or [{}])[0].get("qty") or 1),
        "gatefold": "gatefold" in fmt,
        "a_kant": None, "b_kant": None,
        "aantal_nummers": len(titels),
        "notes": f"herkend op {hoe}: {waarom}",
        "staat_hoes": None,
        "bron": hoe,
        "release_id_auto": rel["id"],
    }


def herken(dc, rec, hoezendir, hint=None):
    """Alle strategieen op volgorde, en de hoes heeft het laatste woord.

    Het beeld was eerst strategie DRIE: het kwam pas aan de beurt als tekst
    niets opleverde. Daardoor werd een plaat die op tekst door de verificatie
    kwam nooit met zijn eigen hoes vergeleken - en juist die tekst is te
    vertrouwen tot er reclame voor de rest van het fonds op de achterkant
    staat. Vijf van de 97 gingen zo mis, waaronder twee promo-persingen en een
    dubbel-LP waar een 7"-single in de hoes zat.

    De toets kost 0,4 seconde per plaat (37s over de hele set, naast een run
    van anderhalve minuut). Dat is te goedkoop om over na te denken.
    """
    plaat, reden = op_tekst(dc, rec, hint)
    if plaat:
        punten = beeld_punten(dc, rec, plaat.get("release_id_auto"), hoezendir)
        plaat["beeld_punten"] = punten
        if punten is None or punten >= BEELD_FOUT:
            # niets te vergelijken, of geen tegenspraak: de tekst blijft staan
            if punten is not None and punten < BEELD_GOED:
                plaat["notes"] += f"; hoes bevestigt dit niet hard ({punten} punten)"
            return plaat, None

        # Een lage score is nog geen tegenspraak. Op de Belgische Decca-persing
        # van Tom Jones (26.225) staan op Discogs alleen twee liggende foto's van
        # het PLAATJE, geen hoes - dan vergelijk je een platenhoes met een label
        # en is vijf punten precies wat je verwacht. Afwezig bewijs is geen
        # tegenbewijs, en die plaat werd zo ten onrechte weggegooid.
        #
        # Daarom pas afwijzen als het beeld iets ANDERS aanwijst: een release die
        # zelf boven de drempel uitkomt. Dat is wat er bij de vier echte fouten
        # gebeurde, en het is precies het bewijs dat hier ontbreekt.
        via, reden2 = op_beeld(dc, rec, hoezendir, hint=hint)
        if via and via.get("release_id_auto") != plaat.get("release_id_auto"):
            via["notes"] += (f"; tekst wees naar {plaat.get('title')!r} "
                             f"maar de hoes wees een andere persing aan "
                             f"({punten} punten voor die van de tekst)")
            return via, None
        plaat["notes"] += (f"; hoes niet te vergelijken ({punten} punten, en het "
                           f"beeld wees niets anders aan)")
        return plaat, None

    plaat, reden2 = op_beeld(dc, rec, hoezendir, hint=hint)
    if plaat:
        return plaat, None

    # Laatste kans voor wat anders op de handmatige lijst belandt.
    plaat, reden3 = laatste_ronde(dc, rec, hoezendir)
    if plaat:
        return plaat, None
    return None, f"{reden}; beeld: {reden2}; breed: {reden3}"
