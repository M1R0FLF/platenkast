#!/usr/bin/env python3
"""
nauwkeurig.py - meet hoe VAAK de gekozen persing aantoonbaar klopt.

Dekking (hoeveel platen herkend) en nauwkeurigheid (hoeveel daarvan de juiste
persing) zijn twee dingen. Dit meet het tweede, en alleen aan bewijs dat op de
hoes zelf staat:

  catalogusnummer  staat het nummer van deze persing op de hoes?
  titel            komt de titel van de release terug in de OCR?
  land             spreekt de hoes het land tegen? ("PRINTED IN HOLLAND")

Een plaat heet ZEKER als het catalogusnummer op de hoes staat. Dat nummer is
uniek per persing, dus dat is geen aanwijzing maar bewijs. Zonder nummer maar
met titel en zonder tegenspraak heet het AANNEMELIJK. Spreekt iets elkaar
tegen, dan VERDACHT.

    py nauwkeurig.py
"""
import json, os, re, sys, argparse, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from velden import kaal, LANDEN
from match import bevat, DICHTBIJ


EUROPEES = {"netherlands", "belgium", "germany", "west germany", "france", "uk",
            "italy", "spain", "ireland", "switzerland", "austria", "denmark",
            "sweden", "norway", "finland", "portugal", "greece", "luxembourg"}


def landen_rijmen(hoes, release):
    """Spreken deze twee elkaar echt tegen?

    Een plaat die Discogs "Europe" noemt en die "PRINTED IN HOLLAND" op de hoes
    heeft staan is geen fout: dat is dezelfde plaat. Europese uitgaven werden in
    een van de Europese landen geperst en dat land staat dan op de hoes. Alleen
    twee verschillende LANDEN spreken elkaar tegen.
    """
    h, r = (hoes or "").lower(), (release or "").lower()
    if not h or not r:
        return True
    if h in r or r in h:
        return True
    if "europe" in r and h in EUROPEES:
        return True
    if "benelux" in r and h in {"netherlands", "belgium", "luxembourg"}:
        return True
    return False


def land_uit_hoes(tekst):
    laag = tekst.lower()
    for k, n in LANDEN:
        if re.search(r"(printed|made|manufactured|pressed)[^.\n]{0,40}" + re.escape(k), laag):
            return n
    return None


def beoordeel(p, g):
    """Het oordeel over één plaat: (niveau, redenen).

    Staat apart zodat de site hetzelfde stempel toont als dit rapport telt.
    Toen dit nog binnen main() zat kon er maar één ding mee gebeuren, en een
    tweede lezer zou de regels overschrijven en stilletjes gaan afwijken.
    """
    tekst = kaal(" ".join([g.get("ocr_achterkant") or "", g.get("ocr_voorkant") or "",
                           g.get("ocr_hoekstrook") or ""]))
    rauw = " ".join([g.get("ocr_achterkant") or "", g.get("ocr_voorkant") or "",
                     g.get("ocr_hoekstrook") or ""])
    cij_hoes = re.sub(r"\D", "", tekst)

    cij_rel = re.sub(r"\D", "", p.get("catno") or "")
    nummer = len(cij_rel) >= 4 and cij_rel in cij_hoes
    titel = bevat(tekst, p.get("title") or "")
    # de artiest telt ook als bewijs: op een verzamelhoes staat de titel
    # soms alleen in sierletters die de OCR niet leest, maar de artiesten
    # wel, en bij een single andersom
    artiest = any(bevat(tekst, deel) for deel in
                  (p.get("artist") or "").split(",")[:2] if len(deel.strip()) > 3)
    hoesland = land_uit_hoes(rauw)
    rl = (p.get("country") or "").lower()
    tegenspraak = bool(hoesland and rl and not landen_rijmen(hoesland, rl))
    ver = (p.get("country") or "").lower().strip() not in DICHTBIJ

    redenen = []
    if tegenspraak:
        redenen.append(f"hoes zegt {hoesland}, persing is {p.get('country')}")
    if ver and (p.get("country") or ""):
        redenen.append(f"onwaarschijnlijk land: {p.get('country')}")
    if redenen:
        return "tegenspraak", redenen
    if nummer:
        return "zeker", ["catalogusnummer staat op de hoes"]
    if titel or artiest:
        return "aannemelijk", ["titel of artiest klopt, niets spreekt tegen"]
    # Geen bewijs is niet hetzelfde als fout bewijs. Bij een donkere of slecht
    # leesbare hoes staat er simpelweg te weinig in de OCR om iets te kunnen
    # zeggen. Die apart houden, anders lijkt het alsof ze mis zijn.
    return "onbevestigd", ["te weinig leesbare tekst om te toetsen"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--platen", default="uit/platen.json")
    ap.add_argument("--groepen", default="uit/groepen.json")
    ap.add_argument("--toon", type=int, default=30)
    a = ap.parse_args()

    platen = json.load(open(a.platen, encoding="utf-8"))
    groepen = {r["id"]: r for r in json.load(open(a.groepen, encoding="utf-8"))}

    tel = collections.Counter()
    verdacht, onbevestigd = [], []
    for p in platen:
        niveau, redenen = beoordeel(p, groepen.get(p["id"], {}))
        tel[niveau] += 1
        if niveau == "tegenspraak":
            verdacht.append((p, redenen))
        elif niveau == "onbevestigd":
            onbevestigd.append(p)

    n = len(platen)
    goed = tel["zeker"] + tel["aannemelijk"]
    toetsbaar = goed + tel["tegenspraak"]
    print(f"{n} herkende platen\n")
    print(f"  ZEKER        {tel['zeker']:>3}  catalogusnummer staat op de hoes")
    print(f"  AANNEMELIJK  {tel['aannemelijk']:>3}  titel of artiest klopt, niets spreekt tegen")
    print(f"  TEGENSPRAAK  {tel['tegenspraak']:>3}  de hoes zegt iets anders")
    print(f"  ONBEVESTIGD  {tel['onbevestigd']:>3}  te weinig OCR om iets te kunnen zeggen")
    print(f"\n  nauwkeurigheid over wat te toetsen is: "
          f"{100*goed/max(toetsbaar,1):.0f}%  ({goed} van {toetsbaar})")
    print(f"  over alles                            : {100*goed/n:.0f}%  ({goed} van {n})")

    if verdacht:
        print(f"\n{len(verdacht)} met tegenspraak:")
        for p, redenen in verdacht[:a.toon]:
            print(f"  {p['id']}  {(p.get('artist') or '')[:28]:<30} "
                  f"{(p.get('title') or '')[:26]:<28} {p.get('country')} {p.get('catno')}")
            for r in redenen:
                print(f"        ! {r}   [{p.get('bron')}]")


if __name__ == "__main__":
    main()
