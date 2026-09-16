#!/usr/bin/env python3
"""
vision.py - haalt betere tekst en een beeldherkenning op bij Google Cloud Vision,
maar alleen voor de platen die lokaal niet lukten.

Waarom dit helpt: de tekstherkenning van Google is duidelijk sterker dan
tesseract op donkere hoezen, glanzend plastic en laag contrast. Dat is precies
waar jouw overblijvers op stranden. De beeldherkenning erbij geeft een beste gok
op wat de hoes voorstelt, bruikbaar als zoekterm.

De verificatie verandert niet: automatch.py blijft controleren of de tracklist
van de gevonden persing terugkomt in de tekst. Er wordt dus nog steeds niets
gegokt.

Kosten: de eerste 1000 eenheden per maand zijn gratis. Dit script vraagt twee
eenheden per plaat (tekst en beeld), dus tot 500 platen per maand gratis. Een
Google Cloud-account met gekoppelde betaalkaart is wel vereist, ook voor de
gratis laag.

Opzetten:
  1. console.cloud.google.com, nieuw project
  2. Cloud Vision API inschakelen
  3. Facturatie koppelen (kaart verplicht, ook gratis)
  4. Een API-sleutel maken onder Credentials
  5. $env:GOOGLE_VISION_KEY="..."

Draaien:
  py vision.py voor_claude.json ruw_vision.json
  py automatch.py ruw_vision.json platen.json --rest voor_claude.json
"""
import os, sys, json, base64, time, argparse
import requests

URL = "https://vision.googleapis.com/v1/images:annotate"


def blok(pad, maxbytes=3_500_000):
    with open(pad, "rb") as fh:
        rauw = fh.read()
    if len(rauw) > maxbytes:
        import cv2
        im = cv2.imread(pad)
        f = 1400.0 / max(im.shape[:2])
        im = cv2.resize(im, (int(im.shape[1] * f), int(im.shape[0] * f)))
        rauw = cv2.imencode(".jpg", im, [cv2.IMWRITE_JPEG_QUALITY, 88])[1].tobytes()
    return base64.b64encode(rauw).decode()


def vraag(sleutel, paden, web=True):
    verzoeken = []
    for p in paden:
        kenmerken = [{"type": "DOCUMENT_TEXT_DETECTION"}]
        if web:
            kenmerken.append({"type": "WEB_DETECTION", "maxResults": 5})
        verzoeken.append({"image": {"content": blok(p)}, "features": kenmerken})
    r = requests.post(URL, params={"key": sleutel},
                      json={"requests": verzoeken}, timeout=90)
    if r.status_code != 200:
        return None, f"{r.status_code} {r.text[:200]}"
    return r.json().get("responses", []), None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("invoer", nargs="?", default="voor_claude.json")
    ap.add_argument("uitvoer", nargs="?", default="ruw_vision.json")
    ap.add_argument("--kit", default="kit")
    ap.add_argument("--geen-web", action="store_true", dest="geen_web",
                    help="alleen tekstherkenning, halveert het verbruik")
    ap.add_argument("--max", type=int, default=0, help="stop na zoveel platen")
    a = ap.parse_args()

    sleutel = os.environ.get("GOOGLE_VISION_KEY")
    if not sleutel:
        sys.exit("GOOGLE_VISION_KEY ontbreekt. Zie de uitleg bovenaan dit bestand.")

    platen = json.load(open(a.invoer, encoding="utf-8"))
    if a.max:
        platen = platen[:a.max]
    eenheden = len(platen) * (1 if a.geen_web else 2)
    print(f"{len(platen)} platen, ongeveer {eenheden} eenheden.")
    if eenheden > 1000:
        print("Let op: boven de gratis 1000 per maand. Gebruik --max of --geen-web.")
    print()

    uit, gebruikt = [], 0
    for i, rec in enumerate(platen, 1):
        beelden = rec.get("beelden") or {}
        # achterkant draagt de tracklist, dus die eerst; anders de voorkant
        pad = beelden.get("achter", {}).get("pad") or beelden.get("voor", {}).get("pad")
        if not pad or not os.path.exists(pad):
            uit.append(rec)
            print(f"[{i}/{len(platen)}] {rec['id']}  geen beeld in kit, overgeslagen")
            continue

        antw, fout = vraag(sleutel, [pad], web=not a.geen_web)
        if fout:
            print(f"[{i}/{len(platen)}] {rec['id']}  FOUT {fout}")
            uit.append(rec)
            if "403" in fout or "API key" in fout:
                print("\nSleutel of facturatie niet in orde. Gestopt.")
                break
            continue
        gebruikt += 1 if a.geen_web else 2

        r0 = antw[0] if antw else {}
        tekst = (r0.get("fullTextAnnotation") or {}).get("text", "")
        nieuw = dict(rec)
        oud = len((rec.get("ocr_achterkant") or "").split())
        if len(tekst.split()) > oud:
            nieuw["ocr_achterkant"] = tekst[:4000]
            nieuw["ocr_bron"] = "google"

        web = r0.get("webDetection") or {}
        gok = [g.get("label") for g in (web.get("bestGuessLabels") or []) if g.get("label")]
        titels = [e.get("pageTitle", "") for e in (web.get("pagesWithMatchingImages") or [])[:4]]
        if gok or titels:
            nieuw["web_gok"] = " | ".join(gok + titels)[:400]

        uit.append(nieuw)
        print(f"[{i}/{len(platen)}] {rec['id']}  {len(tekst.split())} woorden"
              f"{'  gok: ' + gok[0][:45] if gok else ''}")
        json.dump(uit, open(a.uitvoer, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        time.sleep(0.2)

    json.dump(uit, open(a.uitvoer, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    beter = sum(1 for r in uit if r.get("ocr_bron") == "google")
    print(f"\n{a.uitvoer} geschreven. {beter} van {len(uit)} kregen betere tekst.")
    print(f"Ongeveer {gebruikt} eenheden verbruikt.")
    print(f"\nNu:  py automatch.py {a.uitvoer} platen.json --rest voor_claude.json")


if __name__ == "__main__":
    main()
