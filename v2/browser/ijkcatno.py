#!/usr/bin/env python3
"""
ijkcatno.py - wat verandert er als je aan velden.CATNO komt?

    py browser/ijkcatno.py            alleen de kandidaten vergelijken
    py browser/ijkcatno.py --match    ook de gekozen persing (duurt, met netwerk)

Waarom dit bestaat
------------------
Aan `CATNO` zitten is riskant, en dat is hier geen gevoel maar ervaring: met een
ruimer patroon werd Streisands Greatest Hits wel herkend, maar als "Je
M'appelle Barbra" - een advertentie op de achterkant. Fout is erger dan niets,
dus die wijziging ging terug.

Dit script legt het oude en het nieuwe patroon naast elkaar over alle honderd
platen, zonder netwerk, en laat zien wat er anders wordt. Pas als dat klein en
verklaarbaar is heeft het zin om naar de gekozen PERSING te kijken.

De te repareren zaak
--------------------
Rechtsboven op de achterkant van "Ciao Italia '89" staat een blokje met de drie
dragers van dezelfde uitgave. Op de hoes staat er gedrukt:

    2LP : 303.566    de plaat
    2MC : 503.566    de cassette
    2CD : 353.566    de cd

Door het plastic hoesje, met de glans er dwars overheen, leest de OCR dat als:

    21P303566        de plaat     -> CATNO vindt NIETS
    2MC:503.566      de cassette  -> 503.566
    Q-2CD:353.566    de cd        -> 353.566

De schade zit dus niet in het patroon maar in EEN letter: de "L" van 2LP werd
een "1", en de spatie met dubbelepunt ertussen viel weg. Het patroon begint met
\\b, en tussen die "1" en die "P" staat geen woordgrens - dus het nummer van de
PLAAT is onzichtbaar terwijl dat van de twee andere dragers netjes doorkomt. En
die sturen de zoekopdracht naar de verkeerde plaat in dezelfde reeks.

Wat hieronder staat repareert de OCR niet - dat kan van hieruit niet - maar
herkent de VORM die een misgelezen prefix maakt, en haalt het nummer eruit.
"""
import os, re, sys, json, argparse

HIER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HIER)

# Voorstel 2. De eerste poging verplaatste de buitenste \b naar "woordgrens of
# vlak achter een prefix". Gemeten, en op twee manieren mis: hij repareerde
# 163930 NIET - de \b zit ook BINNEN het alternatief \b\d{5,8}\b - en hij brak
# 165216, waar "PY.12124" ineens ook "Y.12124" opleverde omdat een match
# middenin een woord mocht beginnen. Erger dan de kwaal.
#
# Nu andersom: geen ruimere start, maar EEN alternatief erbij dat precies de
# vorm vangt die de OCR hier maakt - een kort prefix van cijfers met een
# hoofdletter, vastgeplakt aan een nummer van vijf of zes cijfers. Het begint
# gewoon op een woordgrens, dus middenin een woord kan er nog steeds niets
# beginnen.
PLAKVORM = (r"\d{1,3}[A-Z]\d{5,6}                       # 21P303566: prefix"
            "\n                                                       "
            "# aan het nummer geplakt\n      | ")

# Wat het alternatief oplevert is "21P303566", en dat vindt Discogs niet. Net
# zoals KANTLETTER de kantletter van een nummer haalt, haalt dit het prefix
# eraf en houdt het nummer van de PLAAT over.
PLAKPREFIX = re.compile(r"^\d{1,3}[A-Z](\d{5,6})$")

ANKER = r"[A-Z]{2,6}[ .\-]?\d{3,6}"


def zonder_plakvorm(patroon):
    """Het patroon zoals het WAS, uit het patroon zoals het IS.

    Andersom dan je verwacht, en met opzet: zo blijft dit een regressietoets die
    ook over een jaar nog draait. Zou ik het nieuwe patroon uit het oude
    opbouwen, dan meet dit script vanaf het moment dat de wijziging erin zit
    niets meer - en een toets die stilletjes niets meer meet is erger dan geen
    toets.
    """
    bron = patroon.pattern
    regels = [r for r in bron.split("\n")
              if "21P303566" not in r and "aan het nummer geplakt" not in r]
    # de losse commentaarregels van het alternatief horen er ook af
    uit, overslaan = [], False
    for r in regels:
        if r.strip().startswith("| [A-Z]{2,6}"):
            overslaan = False
            uit.append(r.replace("| [A-Z]{2,6}", "  [A-Z]{2,6}", 1)
                       if not any("[A-Z]{2,6}" in x for x in uit) else r)
            continue
        if overslaan and r.strip().startswith("#"):
            continue
        uit.append(r)
    schoon = "\n".join(uit)
    assert "21P303566" not in schoon, "de plakvorm zit er nog in"
    return re.compile(schoon)


def kandidaten_met(patroon, tekst, velden):
    """velden.uit_tekst, maar met een ander CATNO-patroon.

    Het filteren (RUIS, WERKNUMMER, KANTLETTER) komt uit velden zelf, zodat
    deze meting alleen het PATROON vergelijkt en niet per ongeluk ook mijn
    kopie van de rest.
    """
    kand, gezien = [], set()
    for m in patroon.finditer(tekst):
        v = " ".join(m.group(1).split())
        if v.upper() in velden.RUIS or velden.WERKNUMMER.match(v):
            continue
        k = velden.KANTLETTER.match(v.upper())
        if k:
            v = k.group(1)
        pp = PLAKPREFIX.match(v.upper())
        if pp:
            v = pp.group(1)
        if v.upper() not in gezien:
            gezien.add(v.upper())
            kand.append(v)
    return kand[:6]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--match", action="store_true",
                    help="ook de gekozen persing opnieuw bepalen (met netwerk)")
    a = ap.parse_args()
    os.chdir(HIER)

    import velden
    nw = velden.CATNO
    oud = zonder_plakvorm(nw)

    groepen = json.load(open("uit/groepen.json", encoding="utf-8"))
    anders, erbij_totaal = [], 0
    for g in groepen:
        tekst = velden.ontplak("\n".join(filter(None, [
            g.get("ocr_achterkant"), g.get("ocr_voorkant"), g.get("ocr_hoekstrook")])))
        a_oud = kandidaten_met(oud, tekst, velden)
        a_nw = kandidaten_met(nw, tekst, velden)
        if a_oud != a_nw:
            erbij = [x for x in a_nw if x not in a_oud]
            weg = [x for x in a_oud if x not in a_nw]
            erbij_totaal += len(erbij)
            anders.append((g["id"], a_oud, a_nw, erbij, weg))

    print(f"{len(groepen)} platen, {len(anders)} met andere kandidaten\n")
    for pid, a_oud, a_nw, erbij, weg in anders:
        print(f"  {pid}")
        print(f"     oud    {a_oud}")
        print(f"     nieuw  {a_nw}")
        if weg:
            print(f"     WEG    {weg}   <-- dit mag niet gebeuren")
    print(f"\n{erbij_totaal} kandidaten erbij, "
          f"{sum(len(w) for *_, w in anders)} verdwenen")

    if not a.match:
        print("\n(--match om te zien of er ook een andere PERSING uitkomt)")
        return

    # De dure helft: alleen voor de platen die veranderden, en alleen die.
    import match as matchmod
    from discogs import Discogs
    dc = Discogs(os.environ.get("DISCOGS_TOKEN"))
    perid = {str(g["id"]): g for g in groepen}
    platen = {str(p["id"]): p for p in json.load(open("uit/platen.json", encoding="utf-8"))}
    print()
    for pid, _, a_nw, *_ in anders:
        rec = dict(perid[str(pid)])
        rec["catno_kandidaten"] = a_nw
        try:
            p, reden = matchmod.herken(dc, rec, "hoezen")
            nieuw_id = p.get("release_id_auto") if p else None
        except Exception as e:
            nieuw_id = f"fout: {e}"
        oud_id = platen.get(str(pid), {}).get("release_id_auto")
        vlag = "" if str(nieuw_id) == str(oud_id) else "   <== ANDERS"
        print(f"  {pid}  was {str(oud_id):10} wordt {str(nieuw_id):10}{vlag}")


if __name__ == "__main__":
    main()
