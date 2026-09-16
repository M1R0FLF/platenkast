#!/usr/bin/env python3
"""
lookup.py - neemt wat Claude Code van de hoezen aflas (platen.json), zoekt de
juiste Discogs-persing, haalt marktprijzen op en schrijft platen.csv.

Geen Anthropic-sleutel nodig. Het aflezen doet Claude Code.

    pip install requests
    $env:DISCOGS_TOKEN="..."        # optioneel maar aangeraden
    py lookup.py platen.json platen.csv

Hervatten: resultaten worden per plaat weggeschreven naar lookup_cache.json.
Voeg later platen toe aan platen.json en draai opnieuw; wat al gedaan is wordt
overgeslagen.
"""
import os, sys, json, time, csv, re, argparse
import requests

UA = "VinylLister/2.0"
API = "https://api.discogs.com"


# ----------------------------------------------------------------- Discogs --

from discogs import Discogs   # één client voor de hele keten, met SQLite-cache


# ------------------------------------------------------------------ matchen --

def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


LAND = {"west germany": "germany", "w. germany": "germany", "brd": "germany",
        "duitsland": "germany", "holland": "netherlands",
        "nederland": "netherlands", "belgie": "belgium", "belgië": "belgium",
        "belgium": "belgium", "uk": "uk", "england": "uk", "engeland": "uk",
        "great britain": "uk", "frankrijk": "france", "italie": "italy",
        "usa": "us", "united states": "us"}

SOORT_HINT = {
    "LP":      (["lp", "album"], ['7"', "single", "maxi", "ep"]),
    "EP":      (["ep"], ["lp", "album", "maxi"]),
    "single7": (['7"', "single", "45 rpm"], ["lp", "album", "maxi", '12"']),
    "maxi12":  (["maxi", '12"', "single"], ["lp", "album", '7"']),
}


def score(c, m):
    s = 0.0
    fmt = " ".join(c.get("format") or []).lower()
    if "vinyl" not in fmt:
        return -99

    soort = (m.get("soort") or "LP").strip()
    if soort in SOORT_HINT:
        good, bad = SOORT_HINT[soort]
        if any(g in fmt for g in good):
            s += 2.5
        if any(b in fmt for b in bad):
            s -= 4.0

    if norm(c.get("catno")) and norm(c.get("catno")) == norm(m.get("catno")):
        s += 5

    # De persing die automatch tegen de tracklist verifieerde. Die is met bewijs
    # gekozen; een zoekresultaat is dat niet. Gemeten: zonder deze voorkeur koos
    # lookup voor 15 van de 54 platen een andere persing, waaronder Will Ferdy
    # (Belgisch) op een Amerikaanse persing zonder enige marktdata.
    if c.get("_geverifieerd"):
        s += 2.5

    wl = LAND.get((m.get("country") or "").lower().strip(),
                  (m.get("country") or "").lower().strip())
    gl = (c.get("country") or "").lower()
    if wl and gl:
        # Het land bepaalt de prijs. Een persing uit het verkeerde land is geen
        # kleine afwijking maar een andere plaat, dus dat weegt zwaar.
        s += 3 if (wl in gl or gl in wl) else -4.0
    try:
        if m.get("year") and abs(int(c.get("year") or 0) - int(m["year"])) <= 1:
            s += 1.5
    except (TypeError, ValueError):
        pass

    notes = (m.get("notes") or "").lower()
    if ("box set" in fmt) != ("box" in notes):
        s -= 2.5
    if m.get("gatefold") and "gatefold" in fmt:
        s += 0.5
    if "club" in fmt and "club" not in notes:
        s -= 1.5
    if "unofficial" in fmt:
        s -= 3
    s += min((c.get("community", {}) or {}).get("have", 0), 4000) / 4000.0
    return s


def match(dc, m):
    seen, cands, pogingen = set(), [], []
    if m.get("barcode"):
        pogingen.append({"barcode": re.sub(r"\D", "", str(m["barcode"])),
                         "format": "Vinyl"})
    if m.get("catno"):
        pogingen.append({"catno": m["catno"], "format": "Vinyl"})
    if m.get("artist") and m.get("title"):
        pogingen.append({"artist": m["artist"], "release_title": m["title"],
                         "format": "Vinyl"})
    if m.get("title"):
        pogingen.append({"q": f"{m.get('artist','')} {m['title']}".strip(),
                         "format": "Vinyl"})
    for t in pogingen:
        for r in dc.search(type="release", **t):
            if r["id"] not in seen:
                seen.add(r["id"])
                cands.append(r)
        if len(cands) >= 3:
            break

    # De geverifieerde persing hoeft niet in de zoekresultaten te staan, en
    # stond er ook vaak niet in. Zet hem er altijd bij.
    vast = m.get("release_id_auto")
    if vast and vast not in seen:
        rel = dc.release(vast)
        if rel:
            fmts = rel.get("formats") or []
            cands.append({
                "id": vast,
                "format": [f.get("name") or "" for f in fmts]
                          + [d for f in fmts for d in (f.get("descriptions") or [])],
                "catno": (rel.get("labels") or [{}])[0].get("catno"),
                "country": rel.get("country"),
                "year": rel.get("year"),
                "community": rel.get("community") or {},
                "_geverifieerd": True,
            })

    if not cands:
        return None, []
    ranked = sorted(cands, key=lambda c: -score(c, m))
    return ranked[0], ranked[1:4]


# ------------------------------------------------------------------- prijs --

def marktdata(dc, rid):
    rel = dc.release(rid) or {}
    out = {
        "release_id": rid,
        "discogs_url": f"https://www.discogs.com/release/{rid}",
        "num_for_sale": rel.get("num_for_sale"),
        "lowest_eur": rel.get("lowest_price"),
        "have": (rel.get("community") or {}).get("have"),
        "want": (rel.get("community") or {}).get("want"),
        "label_discogs": ", ".join(l["name"] for l in (rel.get("labels") or [])[:2]),
        "catno_discogs": (rel.get("labels") or [{}])[0].get("catno"),
        "land_discogs": rel.get("country"),
        "jaar_discogs": rel.get("year"),
        "titel_discogs": rel.get("title"),
        "artiest_discogs": ", ".join(a["name"] for a in (rel.get("artists") or []))[:120],
        "genres": ", ".join((rel.get("genres") or []) + (rel.get("styles") or [])),
        "formats": "; ".join(
            f"{f.get('qty')}x {f.get('name')} "
            f"{' '.join(f.get('descriptions') or [])} {f.get('text') or ''}".strip()
            for f in (rel.get("formats") or [])),
        "tracklist": " | ".join(f"{t.get('position','')} {t['title']}".strip()
                                for t in (rel.get("tracklist") or [])[:26]),
    }
    sug = dc.suggestions(rid)
    if sug:
        for k, veld in (("Near Mint (NM or M-)", "sug_nm"),
                        ("Very Good Plus (VG+)", "sug_vgplus"),
                        ("Very Good (VG)", "sug_vg")):
            v = (sug.get(k) or {}).get("value")
            out[veld] = round(v, 2) if v else None
    return out


def advies(p, soort="LP"):
    single = soort in ("single7", "EP")
    bodem = 3.0 if single else 5.0
    bundel_n, bundel_p = (80, 3.0) if single else (150, 4.0)

    # Twee soorten basis, met een heel andere betekenis.
    # sug_vgplus is een richtprijs voor een plaat in goede staat: daar ga je
    # onder zitten, want 2dehands is een lokale markt met minder kopers.
    # lowest_eur is de goedkoopste die op dat moment wereldwijd te koop staat,
    # meestal een versleten exemplaar. Dat is de bodem, niet het midden, dus
    # daar ga je juist boven zitten.
    if p.get("sug_vgplus"):
        basis, factor = p["sug_vgplus"], 0.85
    elif p.get("lowest_eur"):
        basis, factor = p["lowest_eur"], 1.25
    else:
        return None, "geen marktdata - zelf bekijken"

    n = p.get("num_for_sale") or 0
    want, have = p.get("want") or 0, p.get("have") or 1
    if n > bundel_n and basis < bundel_p:
        return None, "zeer courant, in een lot"
    prijs = basis * factor
    if want / max(have, 1) > 0.15:
        prijs *= 1.15                          # relatief veel vraag
    prijs = max(prijs, bodem)
    return round(prijs * 2) / 2, ("los verkopen" if prijs >= (5 if single else 8)
                                  else "los of lot")


# ------------------------------------------------- titel en advertentietekst --
# Dit is de plek om later je eigen stijl in te zetten.

SOORT_LABEL = {"LP": "LP", "EP": "EP", "single7": 'Single 7"', "maxi12": 'Maxi 12"'}


def advertentie(m, p):
    soort = SOORT_LABEL.get(m.get("soort"), "LP")
    art = m.get("artist") or p.get("artiest_discogs") or ""
    tit = m.get("title") or p.get("titel_discogs") or ""
    lab = p.get("label_discogs") or m.get("label") or ""
    cat = p.get("catno_discogs") or m.get("catno") or ""
    jaar = p.get("jaar_discogs") or m.get("year") or ""
    land = p.get("land_discogs") or m.get("country") or ""

    titel = f"{soort} {art} - {tit}"
    if lab:
        titel += f" - {lab}"
    titel = titel[:60]

    r = [f"{soort}, {lab} {cat}".strip().rstrip(",")]
    if jaar or land:
        r.append(f"Persing {land} {jaar}".strip())
    if p.get("formats"):
        r.append(p["formats"])
    if m.get("soort") in ("single7", "maxi12"):
        ab = " / ".join(x for x in (m.get("a_kant"), m.get("b_kant")) if x)
        if ab:
            r.append(ab)
    elif p.get("tracklist"):
        r.append(p["tracklist"].replace(" | ", "\n"))
    r.append(f"Hoes: {m.get('staat_hoes') or '[invullen]'}. Vinyl: [invullen].")
    if p.get("discogs_url"):
        r.append(p["discogs_url"])
    return titel, "\n".join(x for x in r if x)


# -------------------------------------------------------------------- main --

def prijzen(platen, dc, cachepad="lookup_cache.json", melden=None, stop=None):
    """Zoekt per plaat de persing op en rekent er een vraagprijs bij.

    Meldt onderweg, net als run.keten, zodat kast.py het bedrag kan laten
    oplopen terwijl het nog bezig is in plaats van pas aan het eind.
    """
    zeg = melden or (lambda *x, **k: None)
    stop = stop or (lambda: False)
    cache = json.load(open(cachepad, encoding="utf-8")) if os.path.exists(cachepad) else {}

    rijen = []
    for i, m in enumerate(platen, 1):
        if stop():
            break
        # De persing hoort IN de sleutel. Stond hier alleen het plaat-id, dan
        # bleef een plaat waarvan de keten een andere persing koos stilletjes de
        # oude prijs en de oude titel houden - precies wat er gebeurde toen de
        # beeldtoets vijf verkeerde persingen rechtzette en de CSV ze doodleuk
        # terugzette. Een andere persing is een andere opzoeking.
        rid = str(m.get("id") or (m.get("fotos") or [i])[0])
        sleutel = rid + (f":{m['release_id_auto']}" if m.get("release_id_auto") else "")
        if sleutel in cache:
            rijen.append(cache[sleutel])
            zeg("prijs", klaar=i, totaal=len(platen), rij=cache[sleutel], uit_cache=True)
            continue

        rij = {"id": rid, "fotos": ";".join(m.get("fotos") or [])}
        rij.update({f"gelezen_{k}": v for k, v in m.items()
                    if k not in ("id", "fotos")})
        best, alts = match(dc, m)
        if best:
            p = marktdata(dc, best["id"])
            rij.update(p)
            rij["alternatieven"] = " | ".join(
                f"{c['id']} {c.get('country')} {c.get('year')} "
                f"{' '.join(c.get('format') or [])}" for c in alts)
            rij["vraagprijs"], rij["advies"] = advies(rij, m.get("soort") or "LP")
            rij["titel"], rij["beschrijving"] = advertentie(m, rij)
        else:
            rij["advies"] = "geen Discogs-match - zelf bekijken"

        rijen.append(rij)
        cache[sleutel] = rij
        json.dump(cache, open(cachepad, "w", encoding="utf-8"), ensure_ascii=False)
        zeg("prijs", klaar=i, totaal=len(platen), rij=rij, uit_cache=False)
    return rijen


def schrijf_csv(rijen, pad):
    kop = ["id", "gelezen_soort", "gelezen_artist", "gelezen_title",
           "gelezen_catno", "release_id", "vraagprijs", "advies", "titel",
           "beschrijving", "num_for_sale", "lowest_eur", "sug_vgplus",
           "discogs_url", "alternatieven"]
    kolommen = kop + sorted({k for r in rijen for k in r} - set(kop))
    with open(pad, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=kolommen, extrasaction="ignore")
        w.writeheader()
        w.writerows(rijen)
    return pad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("invoer", nargs="?", default="platen.json")
    ap.add_argument("uitvoer", nargs="?", default="platen.csv")
    ap.add_argument("--cache", default="lookup_cache.json")
    a = ap.parse_args()

    if not os.path.exists(a.invoer):
        sys.exit(f"{a.invoer} bestaat niet. Laat Claude Code eerst de foto's aflezen.")
    platen = json.load(open(a.invoer, encoding="utf-8"))
    if isinstance(platen, dict):
        platen = platen.get("platen", [])

    dc = Discogs(os.environ.get("DISCOGS_TOKEN"))
    if not dc.token:
        print("Geen DISCOGS_TOKEN: geen richtprijs per conditie, en trager.\n")

    def zeg(soort, **k):
        if soort != "prijs":
            return
        r = k["rij"]
        if k["uit_cache"]:
            print(f"[{k['klaar']}/{k['totaal']}] {r['id']} (uit cache)")
        else:
            print(f"[{k['klaar']}/{k['totaal']}] {r.get('gelezen_artist')} - "
                  f"{r.get('gelezen_title')}  -> {r.get('release_id')}  "
                  f"{r.get('vraagprijs')}  ({r.get('advies')})")

    rijen = prijzen(platen, dc, a.cache, zeg)
    schrijf_csv(rijen, a.uitvoer)
    print(f"\n{a.uitvoer} geschreven ({len(rijen)} platen)")


if __name__ == "__main__":
    main()
