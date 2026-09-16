#!/usr/bin/env python3
"""
voortgang.py - hoe ver is het geheel? Draai dit wanneer je maar wil.

    py voortgang.py

Toont altijd de stand van de hele klus (hoeveel van de platen zijn af), dus
ook als er net geen script draait. Schrijft hetzelfde naar VOORTGANG.txt.
"""
import json, os, sys, datetime

HIER = os.path.dirname(os.path.abspath(__file__))


def laad(naam, standaard=None):
    try:
        return json.load(open(os.path.join(HIER, naam), encoding="utf-8"))
    except Exception:
        return standaard


def balk(deel, breed=44):
    vol = max(0, min(breed, int(round(deel * breed))))
    return "[" + "#" * vol + "-" * (breed - vol) + "]"


ruw = laad("ruw2.json", [])
klaar = laad("platen.json", [])
totaal = len(ruw) or 110
af = len(klaar)
deel = min(1.0, af / totaal) if totaal else 0

bron = {}
for r in klaar:
    bron[r.get("bron") or "?"] = bron.get(r.get("bron") or "?", 0) + 1

hart = laad("automatch_voortgang.json") or {}
regels = [
    "",
    f"  {balk(deel)} {100*deel:5.1f}%",
    f"  {af} van {totaal} platen klaar, nog {max(0, totaal-af)} te gaan",
    f"  herkomst: " + ", ".join(f"{k}={v}" for k, v in sorted(bron.items())),
]

# draait er nu een matchronde?
if hart.get("totaal") and hart.get("gedaan", 0) < hart["totaal"]:
    regels.append(f"  automatch loopt: {hart['gedaan']}/{hart['totaal']}")

csv = os.path.join(HIER, "uitvoer", "platen.csv")
if os.path.exists(csv):
    t = datetime.datetime.fromtimestamp(os.path.getmtime(csv))
    regels.append(f"  uitvoer/platen.csv bijgewerkt {t.strftime('%H:%M:%S')}")

regels.append(f"  gekeken om {datetime.datetime.now().strftime('%H:%M:%S')}")
regels.append("")

tekst = "\n".join(regels)
print(tekst)
try:
    open(os.path.join(HIER, "VOORTGANG.txt"), "w", encoding="utf-8").write(tekst + "\n")
except OSError:
    pass
