#!/usr/bin/env python3
"""Waar strandt het? Leest ruw.json en telt.  py diagnose.py"""
import json, re, sys, collections
ruw = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "ruw.json", encoding="utf-8"))
n = len(ruw)
def tel(f): return sum(1 for r in ruw if f(r))
def tekens(r): return len(re.sub(r"\s", "", r.get("ocr_achterkant") or ""))

print(f"{n} platen in ruw.json\n")
print(f"  met catalogusnummer uit OCR : {tel(lambda r: bool(r.get('catno_kandidaten'))):>4}")
print(f"  met streepjescode           : {tel(lambda r: bool(r.get('barcode'))):>4}")
print(f"  met land                    : {tel(lambda r: bool(r.get('land'))):>4}")
print(f"  OCR-kwaliteit goed          : {tel(lambda r: r.get('ocr_kwaliteit')=='goed'):>4}")
print()
emmers = collections.Counter()
for r in ruw:
    t = tekens(r)
    emmers["0 tekens" if t == 0 else "1-99" if t < 100 else "100-349" if t < 350
           else "350-999" if t < 1000 else "1000+"] += 1
print("  tekst op de achterkant:")
for k in ("0 tekens", "1-99", "100-349", "350-999", "1000+"):
    if emmers[k]: print(f"    {k:<10} {emmers[k]:>4}")
print()
print(f"  foto's per plaat: {collections.Counter(len(r.get('fotos') or []) for r in ruw).most_common()}")
z = [r for r in ruw if not r.get("catno_kandidaten") and tekens(r) >= 350]
print(f"\n  {len(z)} platen hebben GEEN nummer maar WEL veel tekst.")
print("  Die zijn met een gewone zoekopdracht op artiest en titel nog te vinden.")
