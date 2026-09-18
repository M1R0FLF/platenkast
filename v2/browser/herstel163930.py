#!/usr/bin/env python3
"""
herstel163930.py - een plaat bijwerken zonder de rest aan te raken.

    py browser/herstel163930.py --proef     laten zien wat er zou veranderen
    py browser/herstel163930.py             het ook doen

Waarom dit bestaat en niet gewoon `py run.py`
---------------------------------------------
De keten opnieuw draaien werkt, maar dan ververst `prijs.py` ook alle honderd
marktprijzen. Dan verandert er niet EEN plaat maar de hele kast, en is niet meer
te zien wat de bugfix deed en wat de markt deed. Dat is geen bijvangst die je
per ongeluk meeneemt.

Dus: alleen 163930. Zijn regel in platen.json, zijn regel in platen.csv, zijn
kandidaten in groepen.json, en daarna collectie.json opnieuw bouwen uit die
bestanden - wat een zuivere afbeelding is en geen nieuwe meting.

Dit script is er voor deze ene plaat en mag weg zodra hij gedraaid is. Het staat
in git zodat navraagbaar blijft wat er precies gebeurd is.
"""
import os, sys, csv, json, shutil, argparse

HIER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HIER)

PID = "163930"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--proef", action="store_true", help="niets wegschrijven")
    a = ap.parse_args()
    os.chdir(HIER)

    import match, prijs, exporteer, velden
    from discogs import Discogs

    groepen = json.load(open("uit/groepen.json", encoding="utf-8"))
    platen = json.load(open("uit/platen.json", encoding="utf-8"))
    g = next(x for x in groepen if str(x["id"]) == PID)

    # De kandidaten opnieuw afleiden uit de OCR die er al ligt. Niet opnieuw
    # LEZEN: de foto's en de uitsnedes zijn niet veranderd, alleen het patroon
    # dat de tekst interpreteert.
    tekst = "\n".join(filter(None, [g.get("ocr_achterkant"), g.get("ocr_voorkant"),
                                    g.get("ocr_hoekstrook")]))
    verse = velden.uit_tekst(tekst)
    oud_kand = g.get("catno_kandidaten") or []
    print(f"kandidaten  was  {oud_kand}")
    print(f"            nu   {verse['catno_kandidaten']}")

    g2 = dict(g, **{k: verse[k] for k in ("catno_kandidaten", "land", "land_gedrukt",
                                          "jaar", "barcode")})

    dc = Discogs(os.environ.get("DISCOGS_TOKEN"))
    nieuw, reden = match.herken(dc, g2, "hoezen")
    if not nieuw:
        sys.exit(f"nu wordt hij NIET herkend ({reden}) - niets gewijzigd")

    oude = next((p for p in platen if str(p["id"]) == PID), {})
    print(f"release     was  {oude.get('release_id_auto')}")
    print(f"            nu   {nieuw.get('release_id_auto')}")
    if str(oude.get("release_id_auto")) == str(nieuw.get("release_id_auto")):
        print("\nzelfde persing, niets te doen")
        return

    rijen_nieuw = prijs.prijzen([nieuw], dc, "lookup_cache.json")
    if not rijen_nieuw:
        sys.exit("prijs.prijzen gaf niets terug - niets gewijzigd")
    rij = rijen_nieuw[0]
    print(f"titel       was  {oude.get('title')!r}")
    print(f"            nu   {rij.get('titel_discogs')!r}")
    print(f"vraagprijs  nu   {rij.get('vraagprijs')}")

    if a.proef:
        print("\n--proef: er is niets weggeschreven")
        return

    # ---- wegschrijven, met een kopie ernaast ----
    for pad in ("uit/platen.json", "uit/platen.csv", "uit/groepen.json",
                "site/publiek/collectie.json"):
        if os.path.exists(pad):
            shutil.copy2(pad, pad + ".voor-163930")

    json.dump([g2 if str(x["id"]) == PID else x for x in groepen],
              open("uit/groepen.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump([nieuw if str(x["id"]) == PID else x for x in platen],
              open("uit/platen.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    # De CSV regel voor regel: de andere 99 blijven letterlijk staan, met hun
    # prijzen van toen. Dat is de hele bedoeling van deze ingreep.
    with open("uit/platen.csv", encoding="utf-8-sig", newline="") as fh:
        lezer = csv.DictReader(fh)
        velden_csv, oude_rijen = lezer.fieldnames, list(lezer)
    vervangen = 0
    uit = []
    for r in oude_rijen:
        if (r.get("id") or "").strip() == PID:
            uit.append({k: rij.get(k, "") for k in velden_csv})
            vervangen += 1
        else:
            uit.append(r)
    if vervangen != 1:
        sys.exit(f"{vervangen} regels met id {PID} in de CSV - niets gewijzigd")
    with open("uit/platen.csv", "w", encoding="utf-8-sig", newline="") as fh:
        s = csv.DictWriter(fh, fieldnames=velden_csv, extrasaction="ignore")
        s.writeheader()
        s.writerows(uit)

    # collectie.json is een afbeelding van die bestanden, dus die mag gewoon
    # opnieuw: er wordt niets nieuws gemeten.
    doc, rest = exporteer.bouw("uit/platen.csv", "uit/platen.json",
                               "uit/groepen.json", "uit/handmatig.json")
    exporteer.duimnagels(doc, "hoezen", "site/publiek/duim")
    oud_doc = json.load(open("site/publiek/collectie.json", encoding="utf-8"))
    json.dump({**oud_doc, "platen": doc, "handmatig": rest,
               "gebouwd": __import__("datetime").datetime.now().isoformat(timespec="seconds")},
              open("site/publiek/collectie.json", "w", encoding="utf-8"),
              ensure_ascii=False)
    print(f"\nklaar. {len(doc)} platen in collectie.json "
          f"(kopieen van voor de ingreep staan als *.voor-163930)")


if __name__ == "__main__":
    main()
