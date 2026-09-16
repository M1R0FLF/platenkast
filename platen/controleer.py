#!/usr/bin/env python3
"""
controleer.py - zoekt verdachte matches in platen.json.

Een verkeerde persing levert een verkeerde prijs en dat merkt niemand nog, dus
het loont om er gericht naar te zoeken. Deze controles vinden geen fouten met
zekerheid, ze wijzen aan wat de moeite van een blik waard is.

    py controleer.py
"""
import json, re, collections, sys

# Deze platen komen uit Belgie. Een persing uit een land waar hier vrijwel
# niets vandaan komt is verdacht, ook als de tracklist klopt: het gaat dan om
# dezelfde plaat maar een andere persing, met een andere prijs.
DICHTBIJ = {"belgium", "netherlands", "germany", "west germany", "france", "uk",
            "europe", "italy", "spain", "ireland", "switzerland", "austria",
            "denmark", "sweden", "norway", "portugal", "greece",
            "france & benelux", "scandinavia", "yugoslavia", "us", "canada"}
VER = {"kenya", "philippines", "japan", "australia", "brazil", "mexico",
       "south africa", "india", "korea", "taiwan", "argentina", "venezuela",
       "israel", "turkey", "new zealand", "singapore", "nigeria", "zimbabwe",
       "german democratic republic (gdr)", "ussr", "russia"}


def main():
    platen = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "platen.json",
                            encoding="utf-8"))
    ruw = {r["id"]: r for r in json.load(open("ruw2.json", encoding="utf-8"))}
    punten = collections.Counter()
    meldingen = []

    for r in platen:
        g = ruw.get(r["id"], {})
        ocr = ((g.get("ocr_achterkant") or "") + " " + (g.get("ocr_voorkant") or "")
               + " " + (g.get("ocr_hoekstrook") or ""))
        kaal = re.sub(r"[^a-z0-9]", "", ocr.lower())
        redenen = []

        land = (r.get("country") or "").lower()
        if land in VER:
            redenen.append(f"verre persing: {r.get('country')}")
        elif land and land not in DICHTBIJ:
            redenen.append(f"ongewoon land: {r.get('country')}")

        if (r.get("label") or "").lower().startswith("not on label"):
            redenen.append("label 'Not On Label'")

        # Staat het catalogusnummer van de gekozen persing echt op de hoes?
        # Vergelijken op de cijferkern, want de schrijfwijze verschilt: Discogs
        # zegt "4 C058-90264" waar de hoes "C058-90264" laat lezen, en dat is
        # hetzelfde nummer. Alleen als de cijfers zelf ontbreken is er wat aan
        # de hand.
        cijfers = re.sub(r"\D", "", r.get("catno") or "")
        if len(cijfers) >= 5 and cijfers not in re.sub(r"\D", "", kaal):
            redenen.append(f"catno {r.get('catno')} niet terug in de OCR")

        # soort tegenover aantal nummers
        n = r.get("aantal_nummers") or 0
        if r.get("soort") == "single7" and n > 4:
            redenen.append(f"single7 maar {n} nummers")
        if r.get("soort") == "LP" and 0 < n <= 2:
            redenen.append(f"LP maar {n} nummers")

        if not r.get("year"):
            redenen.append("geen jaar")

        if redenen:
            punten[len(redenen)] += 1
            meldingen.append((len(redenen), r, redenen))

    meldingen.sort(key=lambda m: -m[0])
    print(f"{len(platen)} platen, {len(meldingen)} met een opmerking\n")
    for n, r, redenen in meldingen:
        print(f"  {r['id']}  {(r.get('artist') or '')[:30]} - {(r.get('title') or '')[:34]}")
        print(f"      {r.get('country')} {r.get('year')} {r.get('catno')} ({r.get('soort')})")
        for x in redenen:
            print(f"      ! {x}")
    print(f"\nzonder opmerking: {len(platen)-len(meldingen)}")


if __name__ == "__main__":
    main()
