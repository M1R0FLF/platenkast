#!/usr/bin/env python3
"""
vulpersing.py - achteraf uitzoeken hoe uniek elk catalogusnummer is.

    py vulpersing.py --proef      laten zien wat er zou veranderen
    py vulpersing.py              het ook doen

Waarom dit bestaat
------------------
`match.herken` vult sinds vandaag `persing_delers` in: hoeveel ANDERE persingen
hetzelfde catalogusnummer dragen. `nauwkeurig.beoordeel` heeft dat nodig om niet
"zeker" te zeggen waar het nummer de uitgave vastlegt en niet de persing.

Platen die eerder herkend zijn hebben dat veld niet. Zonder achteraf invullen
zou de hele kast op "uitgave" blijven staan tot je alles opnieuw draait - en
opnieuw draaien ververst ook alle marktprijzen, waardoor je niet meer kunt zien
wat deze correctie deed en wat de markt deed. Dezelfde afweging als bij
`browser/herstel163930.py`.

Dus: alleen dit ene veld erbij, en daarna `collectie.json` opnieuw bouwen uit de
bestanden die er al liggen. Dat laatste is een afbeelding, geen nieuwe meting.

Herhaalbaar: draai hem nog eens en hij kijkt alles opnieuw na. Discogs kan van
gedachten veranderen - er komen persingen bij.
"""
import os, sys, json, shutil, argparse, collections

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HIER)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--platen", default="uit/platen.json")
    ap.add_argument("--groepen", default="uit/groepen.json")
    ap.add_argument("--proef", action="store_true", help="niets wegschrijven")
    a = ap.parse_args()
    os.chdir(HIER)

    import match, nauwkeurig, exporteer
    from discogs import Discogs

    platen = json.load(open(a.platen, encoding="utf-8"))
    groepen = {str(r["id"]): r for r in json.load(open(a.groepen, encoding="utf-8"))}
    dc = Discogs(os.environ.get("DISCOGS_TOKEN"))

    voor = collections.Counter()
    for p in platen:
        voor[nauwkeurig.beoordeel(p, groepen.get(str(p["id"]), {}))[0]] += 1

    print(f"{len(platen)} platen nakijken bij Discogs...\n")
    stil = 0
    for i, p in enumerate(platen, 1):
        n, landen = match.deelt_nummer(dc, p)
        if p.get("persing_delers") == n:
            stil += 1
        p["persing_delers"] = n
        p["persing_landen"] = landen
        if i % 25 == 0:
            print(f"  {i}/{len(platen)}", flush=True)

    na = collections.Counter()
    for p in platen:
        na[nauwkeurig.beoordeel(p, groepen.get(str(p["id"]), {}))[0]] += 1

    print("\n             was    wordt")
    for niveau in ("zeker", "uitgave", "aannemelijk", "onbevestigd", "tegenspraak"):
        if voor[niveau] or na[niveau]:
            pijl = "" if voor[niveau] == na[niveau] else "   <--"
            print(f"  {niveau:<12} {voor[niveau]:>3}    {na[niveau]:>3}{pijl}")

    zonder = [p for p in platen if p.get("persing_delers") is None]
    if zonder:
        print(f"\n  {len(zonder)} zonder uitsluitsel (geen bruikbaar nummer, of "
              f"Discogs gaf niets)")

    if a.proef:
        print("\n--proef: er is niets weggeschreven")
        return

    for pad in (a.platen, "site/publiek/collectie.json"):
        if os.path.exists(pad):
            shutil.copy2(pad, pad + ".voor-persing")
    json.dump(platen, open(a.platen, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    doc, rest = exporteer.bouw("uit/platen.csv", a.platen, a.groepen,
                               "uit/handmatig.json")
    exporteer.duimnagels(doc, "hoezen", "site/publiek/duim")
    oud = json.load(open("site/publiek/collectie.json", encoding="utf-8"))
    telling = collections.Counter(p["oordeel"] for p in doc)
    json.dump({**oud, "platen": doc, "handmatig": rest,
               "samenvatting": {**oud.get("samenvatting", {}),
                                "oordeel": dict(telling)},
               "gebouwd": __import__("datetime").datetime.now().isoformat(
                   timespec="seconds")},
              open("site/publiek/collectie.json", "w", encoding="utf-8"),
              ensure_ascii=False)
    print(f"\nklaar. {len(doc)} platen in collectie.json "
          f"(kopieen van voor de ingreep staan als *.voor-persing)")


if __name__ == "__main__":
    main()
