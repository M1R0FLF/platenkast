#!/usr/bin/env python3
"""
ijkpersing.py - belooft het stempel "zeker" meer dan het catalogusnummer waarmaakt?

    py meten/ijkpersing.py            meten en de uitslag tonen
    py meten/ijkpersing.py --toon 0   alleen de telling

Waar dit over gaat
------------------
`nauwkeurig.beoordeel` geeft "zeker" zodra het catalogusnummer van de gekozen
persing in de OCR van de hoes staat, met als onderbouwing: *dat nummer is uniek
per persing, dus dat is geen aanwijzing maar bewijs*.

Die onderbouwing klopt niet altijd. Labels gaven hetzelfde nummer aan persingen
in verschillende landen - dezelfde hoes, hetzelfde nummer, een andere fabriek.
Dan legt het nummer de UITGAVE vast en niet de PERSING, en belooft "zeker" meer
dan er gelezen is. Dat is precies het soort belofte dat deze kast nergens anders
doet (zie "liever niets dan iets verkeerds" in LEESMIJ).

Hoe het gemeten wordt
---------------------
Per plaat het catalogusnummer van de GEKOZEN persing bij Discogs opzoeken. Let
op: die zoekopdracht is los - zoeken op "303.566" geeft ook een Canadese plaat
met nummer "BDAY139LP" terug. Dus zelf exact nafilteren op het genormaliseerde
nummer.

Een treffer telt alleen als TWEELING wanneer het dezelfde uitgave is: zelfde
artiest en titel. Een andere plaat met toevallig hetzelfde nummer is geen
probleem, want die was op de hoestekst al uit te sluiten.

En dan de vraag die beslist: staat er een LAND op de hoes ("PRINTED IN
HOLLAND")? Zo ja, en dat land wijst maar een van de tweelingen aan, dan is het
nummer samen met het land nog steeds bewijs. Zo niet, dan niet.

Uitslag op 2026-09-19
---------------------
    100 platen, bij 77 staat het catalogusnummer op de hoes

      uniek            33  het nummer wijst een persing aan
      land beslist      0  meer persingen, maar de hoes noemt het land
      DUBBELZINNIG     44  meer persingen, geen land op de hoes

Naar aanleiding daarvan heet die 44 nu "uitgave" en niet meer "zeker". Dit
script blijft staan om dat na te rekenen: wat "zeker" heet hoort nul delers te
hebben.
"""
import os, re, sys, json, argparse, collections

HIER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HIER)

from velden import kaal
from nauwkeurig import land_uit_hoes, landen_rijmen


# De drie filters die bepalen wat een tweeling is stonden hier eerst. Ze staan
# nu in `match.deelt_nummer`, want de KETEN moet ze toepassen en niet alleen dit
# rapport. Twee kopieen van dezelfde regel lopen uit elkaar, en dan meet dit
# script iets anders dan de site toont.
from match import deelt_nummer


def ocr_van(g):
    return " ".join(filter(None, [g.get("ocr_achterkant"), g.get("ocr_voorkant"),
                                  g.get("ocr_hoekstrook")]))


def meet(dc, platen, groepen):
    uit = []
    for p in platen:
        g = groepen.get(str(p["id"])) or {}
        n, landen = deelt_nummer(dc, p)
        uit.append({"id": str(p["id"]), "artiest": p.get("artist"),
                    "titel": p.get("title"), "catno": p.get("catno"),
                    "land": p.get("country"), "soort": p.get("soort"),
                    "release": p.get("release_id_auto"),
                    "hoesland": land_uit_hoes(ocr_van(g)),
                    "delers": n, "landen": landen,
                    "fout": None if n is not None else "niet te bepalen"})
    return uit


def beslist_het_land(rij):
    """Wijst het land op de hoes precies EEN van de kandidaten aan?

    Dit is de afweging die uit `match.deelt_nummer` is weggelaten. Hij staat
    hier nog omdat dit rapport moet KUNNEN laten zien dat weglaten terecht was:
    zodra dit getal boven nul komt, is de keten te streng en hoort de afweging
    er alsnog in.
    """
    if not rij["hoesland"] or not rij["delers"]:
        return False
    kandidaten = [rij["land"]] + list(rij["landen"])
    passend = [1 for land in kandidaten if landen_rijmen(rij["hoesland"], land or "")]
    return len(passend) == 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--platen", default="uit/platen.json")
    ap.add_argument("--groepen", default="uit/groepen.json")
    ap.add_argument("--toon", type=int, default=30)
    ap.add_argument("--uit", default="", help="de meting ook wegschrijven")
    a = ap.parse_args()
    os.chdir(HIER)

    from discogs import Discogs
    import nauwkeurig

    platen = json.load(open(a.platen, encoding="utf-8"))
    groepen = {str(r["id"]): r for r in json.load(open(a.groepen, encoding="utf-8"))}
    dc = Discogs(os.environ.get("DISCOGS_TOKEN"))

    # De platen waar het catalogusnummer GELEZEN is, dus "zeker" of "uitgave".
    # Bij de rest zegt het stempel niets over het nummer en valt er niets te
    # toetsen.
    #
    # Let op de valkuil: hier stond eerst `== "zeker"`. Dat werkte zolang
    # `beoordeel` "zeker" gaf zodra het nummer gelezen was - maar precies dat is
    # veranderd, en toen selecteerde dit script nul platen en meldde opgewekt
    # dat er niets mis was. Een toets die zichzelf uitschakelt zodra de fout
    # gerepareerd lijkt, is geen toets.
    gelezen = [p for p in platen
               if nauwkeurig.beoordeel(p, groepen.get(str(p["id"]), {}))[0]
               in ("zeker", "uitgave")]
    print(f"{len(platen)} platen, bij {len(gelezen)} staat het "
          f"catalogusnummer op de hoes\n")

    uitslag = meet(dc, gelezen, groepen)

    tel = collections.Counter()
    overbelooft = []
    for r in uitslag:
        if r["fout"]:
            tel["fout"] += 1
        elif not r["delers"]:
            tel["uniek"] += 1
        elif beslist_het_land(r):
            tel["land beslist"] += 1
        else:
            tel["dubbelzinnig"] += 1
            overbelooft.append(r)

    print(f"  uniek           {tel['uniek']:>3}  het nummer wijst een persing aan")
    print(f"  land beslist    {tel['land beslist']:>3}  meer persingen, maar de hoes noemt het land")
    print(f"  DUBBELZINNIG    {tel['dubbelzinnig']:>3}  meer persingen, geen land op de hoes")
    if tel["fout"]:
        print(f"  fout            {tel['fout']:>3}  niet te meten")

    n = len(uitslag) or 1
    print(f"\n  \"zeker\" belooft te veel bij {tel['dubbelzinnig']} van de {len(uitslag)} "
          f"({100*tel['dubbelzinnig']/n:.0f}%)")

    if a.toon and overbelooft:
        print(f"\nDe dubbelzinnige:")
        for r in overbelooft[:a.toon]:
            landen = ", ".join(r["landen"]) or "onbekend"
            print(f"  {r['id']}  {(r['artiest'] or '')[:24]:<26}"
                  f"{(r['titel'] or '')[:24]:<26} {r['catno']:<14}")
            print(f"        gekozen: {r['land']}  |  ook: {landen}  "
                  f"({r['delers']} andere)")

    if a.uit:
        json.dump(uitslag, open(a.uit, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(f"\n-> {a.uit}")


if __name__ == "__main__":
    main()
