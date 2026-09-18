#!/usr/bin/env python3
"""
hersnij.py - snijdt de hoes opnieuw uit, met de hoes op Discogs als mal.

Het probleem
------------
knip.zoek moet de rand van de hoes vinden zonder te weten hoe die hoes
eruitziet. Het zoekt de overgang tussen vloerkleur en hoes, en dat gaat op
twee manieren mis die allebei voorkomen:

    te krap   de rand loopt dwars door de hoes. Gene Pitney hield 41 procent
              van zijn hoes over, Chamfort 48.
    te ruim   er zit vloer omheen. Shirley Bassey was voor de helft parket.

Gemeten over 90 voorkanten: 16 fout.

De oplossing
------------
Zodra de persing bekend is hoeft de rand niet meer gezocht te worden, want
hij is bekend. De homografie tussen de ORIGINELE foto en de hoes op Discogs
zegt waar de vier hoeken van die hoes in de foto liggen, en dan is uitsnijden
het rechttrekken van die vierhoek. Meteen goed gedraaid ook, want de
homografie bevat de draaiing.

Dat moet op het origineel en niet op de uitsnede: bij een te krappe uitsnede
zijn de ontbrekende pixels er niet meer, en in fotos/ staan ze nog. Aan
fotos/ wordt niets veranderd - er wordt alleen uit gelezen.

De vierhoek gaat naar uit/snijquads.json zodat foto.py hem de volgende keer
meteen pakt. Zonder dat zou een verhoging van knip.VERSIE de uitsnede
stilletjes terugzetten naar de gezochte rand.

    py hersnij.py --proef     meten, niets aanraken
    py hersnij.py             opnieuw snijden
"""
import os, sys, json, argparse
import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import beeld
from discogs import Discogs
from beeldtoets import cover_urls

# Hoger dan de drempel van stand.py: daar hoefde alleen de HOEK te kloppen en
# hier hangt de hele uitsnede eraan. Een homografie op twintig punten levert
# een vierhoek die nergens op slaat.
DREMPEL = 60

QUADS = "uit/snijquads.json"


def _homografie(kf, kh):
    kpA, desA = kf
    kpB, desB = kh
    if desA is None or desB is None or len(desA) < 10 or len(desB) < 10:
        return None, 0
    bf = cv2.BFMatcher(cv2.NORM_HAMMING)
    try:
        paren = bf.knnMatch(desA, desB, k=2)
    except cv2.error:
        return None, 0
    goed = [m for m, n in (p for p in paren if len(p) == 2)
            if m.distance < 0.75 * n.distance]
    if len(goed) < 8:
        return None, 0
    src = np.float32([kpA[m.queryIdx].pt for m in goed]).reshape(-1, 1, 2)
    dst = np.float32([kpB[m.trainIdx].pt for m in goed]).reshape(-1, 1, 2)
    try:
        H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
    except cv2.error:
        return None, 0
    if H is None or mask is None:
        return None, 0
    return H, int(mask.sum())


def _deugt(q, vorm_orig, verhouding):
    """Is deze vierhoek een geloofwaardige hoes in deze foto?"""
    h, w = vorm_orig
    if not np.isfinite(q).all():
        return False
    # ruim buiten de foto is onmogelijk; een beetje eroverheen mag, want een
    # hoes mag de rand van de foto raken
    if (q.min() < -0.08 * max(h, w) or q[:, 0].max() > 1.08 * w
            or q[:, 1].max() > 1.08 * h):
        return False
    opp = abs(cv2.contourArea(q.astype(np.float32)))
    if not (0.08 * h * w < opp < 1.05 * h * w):
        return False
    z = [float(np.linalg.norm(q[i] - q[(i + 1) % 4])) for i in range(4)]
    if min(z) < 40:
        return False
    # overstaande zijden ongeveer gelijk, anders is het geen rechthoek maar
    # een scheefgetrokken homografie
    if abs(z[0] - z[2]) / max(z) > 0.18 or abs(z[1] - z[3]) / max(z) > 0.18:
        return False
    r = ((z[0] + z[2]) / 2) / max((z[1] + z[3]) / 2, 1e-6)
    return abs(r - verhouding) / verhouding <= 0.18


def mallen(refs):
    """Kenmerken en afmetingen van de hoezen, een keer per PERSING.

    Stond dit in quad_van, dan werd voor elke foto van dezelfde plaat opnieuw
    ORB over dezelfde drie Discogs-hoezen gehaald - drie keer het werk bij een
    gatefold met drie foto's. De hoes verandert niet tussen twee foto's van
    dezelfde plaat.
    """
    uit = []
    for hoes in refs:
        kh = beeld.kenmerken(hoes)
        if kh[1] is None:
            continue
        hh, hw = beeld._klaar(hoes).shape[:2]
        uit.append((kh, hw, hh))
    return uit


def quad_van(origineel, mal):
    """(vierhoek in originele pixels, punten, (breedte, hoogte) van de mal).

    De hoeken staan op volgorde van de HOES - linksboven, rechtsboven,
    rechtsonder, linksonder - dus na rechttrekken staat hij meteen rechtop.
    """
    vol = cv2.imread(origineel)
    if vol is None:
        return None, 0, None
    kf = beeld.kenmerken(vol)
    if kf[1] is None:
        return None, 0, None
    schaal = vol.shape[1] / float(beeld._klaar(vol).shape[1])

    beste = (None, 0, None)
    for kh, hw, hh in mal:
        H, n = _homografie(kf, kh)
        if H is None or n <= beste[1]:
            continue
        try:
            Hi = np.linalg.inv(H)
        except np.linalg.LinAlgError:
            continue
        hoeken = np.float32([[[0, 0]], [[hw, 0]], [[hw, hh]], [[0, hh]]])
        q = cv2.perspectiveTransform(hoeken, Hi).reshape(4, 2) * schaal
        if not _deugt(q, vol.shape[:2], hw / float(hh)):
            continue
        beste = (q, n, (hw, hh))
    return beste


def snijd_met(origineel, q, verhouding, zijde=3200):
    vol = cv2.imread(origineel)
    if vol is None:
        return None
    if verhouding >= 1:
        W, H = zijde, max(1, int(round(zijde / verhouding)))
    else:
        H, W = zijde, max(1, int(round(zijde * verhouding)))
    dst = np.array([[0, 0], [W - 1, 0], [W - 1, H - 1], [0, H - 1]], "float32")
    M = cv2.getPerspectiveTransform(q.astype("float32"), dst)
    return cv2.warpPerspective(vol, M, (W, H), flags=cv2.INTER_CUBIC)


def origineel_van(stam, fotodir):
    for ext in (".jpg", ".jpeg", ".JPG", ".JPEG", ".png", ".PNG"):
        kand = os.path.join(fotodir, stam + ext)
        if os.path.exists(kand):
            return kand
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--platen", default="uit/platen.json")
    ap.add_argument("--fotos", default="../platen/fotos")
    ap.add_argument("--hoezen", default="hoezen")
    ap.add_argument("--zijde", type=int, default=3200)
    ap.add_argument("--proef", action="store_true")
    a = ap.parse_args()

    platen = json.load(open(a.platen, encoding="utf-8"))
    dc = Discogs(os.environ.get("DISCOGS_TOKEN"))
    from knip import autolevel

    quads = json.load(open(QUADS, encoding="utf-8")) if os.path.exists(QUADS) else {}
    gedaan = overgeslagen = 0
    for i, p in enumerate(platen, 1):
        rid = p.get("release_id_auto")
        if not rid:
            continue
        mal = mallen([x for x in (beeld.haal(u) for u in cover_urls(dc, rid)[0][:3])
                      if x is not None])
        if not mal:
            continue
        for naam in (p.get("fotos") or []):
            stam = os.path.splitext(os.path.basename(naam))[0]
            orig = origineel_van(stam, a.fotos)
            if orig is None:
                continue
            q, n, vorm = quad_van(orig, mal)
            if q is None or n < DREMPEL:
                overgeslagen += 1
                print(f"[{i:>3}] {stam:<26} {n:>4} pt  overgeslagen", flush=True)
                continue
            verhouding = vorm[0] / float(vorm[1])
            gedaan += 1
            print(f"[{i:>3}] {stam:<26} {n:>4} pt  opnieuw gesneden", flush=True)
            if a.proef:
                continue
            beeldje = snijd_met(orig, q, verhouding, a.zijde)
            if beeldje is None:
                continue
            cv2.imwrite(os.path.join(a.hoezen, stam + ".jpg"), autolevel(beeldje),
                        [cv2.IMWRITE_JPEG_QUALITY, 92])
            quads[stam] = {"quad": q.tolist(), "verhouding": verhouding,
                           "punten": n}

    if not a.proef:
        os.makedirs(os.path.dirname(QUADS), exist_ok=True)
        json.dump(quads, open(QUADS, "w", encoding="utf-8"), ensure_ascii=False)
    print("\n" + "=" * 56)
    print(f"  opnieuw gesneden   {gedaan}")
    print(f"  overgeslagen       {overgeslagen}"
          f"  (te weinig punten of geen nette vierhoek)")
    if not a.proef:
        print(f"\n-> {QUADS}")


if __name__ == "__main__":
    main()
