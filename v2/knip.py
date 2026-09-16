#!/usr/bin/env python3
"""
knip.py - hoes uit de foto snijden en rechtop zetten.

Opnieuw opgezet, want de oude aanpak had twee fouten die elkaar versterkten.

1. EEN METHODE MET EEN TERUGVAL IS NIET BETROUWBAAR.
   Er was lijndetectie, en als die niets vond een kleurmasker. Maar de fout was
   zelden "niets gevonden"; de fout was "met overtuiging het verkeerde
   gevonden". Een terugval helpt daar niet tegen: die springt nooit aan.

   Hier levert elke methode KANDIDATEN, en een aparte meetlat kiest. De meetlat
   weet niets van hoe een kandidaat gevonden is, dus een zelfverzekerde
   misser verliest gewoon van een goede.

2. DE VERHOUDING WERD TE VROEG AFGEDWONGEN.
   De oude eis was: een gatefold ligt breder dan hoog. Dat klopt voor het
   EINDRESULTAAT, maar niet voor de foto: een opengeklapte hoes ligt net zo
   vaak op zijn kant op de vloer, en is dan 1:2. Drie van de vijf slechtste
   uitsnedes waren precies dat - de hoes was al perfect gevonden (0,49, 0,51,
   0,54) en werd weggegooid. Daarna maakte de terugval er een reep van.

   Hier mag 1:2 net zo goed als 2:1. Rechtop zetten is een latere stap.

De meetlat zelf is de kern. Voor elke kandidaat-vierhoek:

    buiten    ligt er vloer vlak BUITEN de rand?   (dan is dit de buitenrand)
    binnen    ligt er geen vloer vlak BINNEN?      (dan zit er geen vloer bij)
    vorm      hoe dicht bij 1:1, 2:1 of 1:2?
    vulling   is het vlak echt een rechthoek?

"buiten" is wat een halve gatefold uitsluit: langs de vouw ligt geen vloer maar
hoes, en dat ziet de meetlat.
"""
import os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import cv2
import numpy as np

cv2.setNumThreads(1)

VERHOUDINGEN = (1.0, 2.0, 0.5)    # vierkante hoes, gatefold liggend of staand

# Ophogen zodra het snijden of rechtzetten verandert. foto.py zet dit nummer in
# de OCR-sleutel en in een stempel naast de uitsnedes, zodat een verbetering
# niet stilletjes over oude uitsnedes heen leest.
VERSIE = 2

# Werkbreedte waarop gezocht wordt. Stond op 900 en dat was zonde: de zware
# stappen (morfologie op vijf maskers, grabcut, bilateraal filter) schalen met
# het kwadraat, dus 900 -> 560 scheelt ruim de helft van het rekenwerk.
#
# Het kan omlaag omdat `verfijn` er is. Een masker hoeft alleen ONGEVEER goed te
# zijn - de rand wordt daarna toch nog los bijgeschoven - en die verfijning
# werkt op dezelfde kleine kaart. Een pixel hier is nog geen twee promille van
# de foto, en de perspectiefcorrectie haalt de echte pixels uit het origineel.
KLEIN = 560

# Boven dit cijfer is de uitsnede goed genoeg om de dure tweede ronde over te
# slaan. Niet hoog gekozen: het gaat er niet om perfect te zijn maar om te
# weten wanneer doorzoeken nog iets kan opleveren.
GOED_GENOEG = 0.82


# ---------- vloermodel -------------------------------------------------------

def vloer_model(sm):
    """Kleur van de vloer, uit de vier hoeken van de foto.

    De oude versie nam de mediaan van de hele randstrook. Bij een hoes die tot
    aan de boven- en onderrand doorloopt - en dat is bij een staande gatefold
    de regel - zit daar zoveel hoes in dat de "vloerkleur" die van de hoes
    wordt. De hoeken blijven wel vloer: een rechthoek die alle vier de hoeken
    haalt vult de hele foto.

    Alleen a en b uit Lab, niet de helderheid L. Schaduw naast de hoes is
    donkerder hout, maar nog steeds hout.
    """
    lab = cv2.cvtColor(cv2.bilateralFilter(sm, 9, 50, 50), cv2.COLOR_BGR2LAB)
    ab = lab[:, :, 1:].astype(np.float32)
    h, w = ab.shape[:2]
    kh, kw = int(h * .13), int(w * .13)
    hoeken = np.concatenate([ab[:kh, :kw].reshape(-1, 2), ab[:kh, -kw:].reshape(-1, 2),
                             ab[-kh:, :kw].reshape(-1, 2), ab[-kh:, -kw:].reshape(-1, 2)])
    med = np.median(hoeken, 0)
    tol = max(6.0, float(np.percentile(np.linalg.norm(hoeken - med, axis=1), 90)))
    return ab, med, tol


def is_vloer(ab, med, tol, x, y):
    h, w = ab.shape[:2]
    if not (0 <= x < w and 0 <= y < h):
        return True          # buiten de foto: daar lag de vloer ook
    return float(np.linalg.norm(ab[y, x] - med)) < tol


# ---------- lijndetectie -----------------------------------------------------
#
# Overgenomen uit uitsnijden.py van v1, want gemeten over 60 foto's levert dit
# de beste uitsnede in 35 gevallen - meer dan alle maskers samen. De rest van
# dat bestand (een eigen opdrachtregel, tesseract-OSD, contactvellen) is
# vervallen en staat hier niet meer.
#
# De vondst die het waard maakt: de Hough-lijnen worden gezocht op de rand van
# de ACHTERGRONDKAART, niet op de grijswaarden. Daardoor levert de illustratie
# op de hoes zelf geen kandidaatlijnen op, en dat was de reden dat een eerdere
# versie op de binnenkader van de hoes uitkwam in plaats van op de buitenrand.

LIJNBREEDTE = 900       # de lijnzoeker wil meer pixels dan de maskers
RTOL = {1.0: .12, 2.0: .07}      # gatefold strenger: 1,86-2,14, geen 1,8


def _achtergrond(sm):
    """a en b uit Lab langs de rand: de kleur van de vloer, zonder helderheid,
    zodat schaduw naast de hoes nog steeds als vloer telt."""
    lab = cv2.cvtColor(cv2.bilateralFilter(sm, 9, 50, 50), cv2.COLOR_BGR2LAB).astype(np.float32)
    ab = lab[:, :, 1:]
    h, w = ab.shape[:2]
    m = int(.035 * min(h, w))
    bd = np.concatenate([ab[:m].reshape(-1, 2), ab[-m:].reshape(-1, 2),
                         ab[:, :m].reshape(-1, 2), ab[:, -m:].reshape(-1, 2)])
    med = np.median(bd, 0)
    tol = max(6., float(np.percentile(np.linalg.norm(bd - med, axis=1), 85)))
    return ab, med, tol


def _lijn(s):
    x1, y1, x2, y2 = s
    d = np.array([x2 - x1, y2 - y1], float)
    L = np.linalg.norm(d)
    if L < 1:
        return None
    d /= L
    n = np.array([-d[1], d[0]])
    return (np.arctan2(d[1], d[0]) % np.pi, abs(float(n @ np.array([x1, y1]))),
            np.array([x1, y1], float), d, L)


def _bundels(edge, minlen, keep):
    """Lijnstukken groeperen in twee loodrechte bundels: de horizontale en de
    verticale randen van de hoes."""
    segs = cv2.HoughLinesP(edge, 1, np.pi / 360, 70, minLineLength=minlen, maxLineGap=30)
    if segs is None:
        return None
    L = [x for x in (_lijn(s) for s in segs.reshape(-1, 4)) if x]
    if len(L) < 4:
        return None
    a = np.array([l[0] for l in L])
    gew = np.array([l[4] for l in L])
    hh, _ = np.histogram(a, 180, (0, np.pi), weights=gew)
    hh = np.convolve(np.r_[hh, hh, hh], np.ones(7) / 7, "same")[180:360]
    a0 = np.argmax(hh) * np.pi / 180
    g1, g2 = [], []
    for l in L:
        d = abs(((l[0] - a0 + np.pi / 2) % np.pi) - np.pi / 2)
        if d < np.deg2rad(12):
            g1.append(l)
        elif abs(d - np.pi / 2) < np.deg2rad(12):
            g2.append(l)

    def dun(g):
        g = sorted(g, key=lambda x: x[1])
        o = []
        for l in g:
            if o and abs(l[1] - o[-1][1]) < 14:
                if l[4] > o[-1][4]:
                    o[-1] = l
            else:
                o.append(l)
        return sorted(o, key=lambda x: -x[4])[:keep]

    g1, g2 = dun(g1), dun(g2)
    return (g1, g2) if len(g1) >= 2 and len(g2) >= 2 else None


def _snijpunt(a, b):
    A = np.array([a[3], -b[3]]).T
    if abs(np.linalg.det(A)) < 1e-8:
        return None
    t = np.linalg.solve(A, b[2] - a[2])
    return a[2] + a[3] * t[0]


def detect(img, ratios=VERHOUDINGEN, rtol=.12):
    """Beste rechthoek uit twee horizontale en twee verticale randlijnen."""
    import itertools
    h, w = img.shape[:2]
    s = LIJNBREEDTE / float(w)
    sm = cv2.resize(img, (LIJNBREEDTE, int(h * s)), interpolation=cv2.INTER_AREA)
    H, Wd = sm.shape[:2]
    opp_foto = H * Wd
    ab, med, tol = _achtergrond(sm)

    d = np.linalg.norm(ab - med, axis=2)
    d = cv2.normalize(d, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    d = cv2.GaussianBlur(cv2.morphologyEx(d, cv2.MORPH_CLOSE,
                                          np.ones((9, 9), np.uint8), iterations=2), (7, 7), 0)
    E_bg = cv2.Canny(d, 40, 120)
    grijs = cv2.bilateralFilter(cv2.cvtColor(sm, cv2.COLOR_BGR2GRAY), 7, 60, 60)
    E_gr = cv2.Canny(grijs, 30, 90)
    sup = cv2.dilate(cv2.bitwise_or(E_bg, E_gr), np.ones((3, 3), np.uint8), iterations=2)

    G = (_bundels(E_bg, int(.18 * min(H, Wd)), 12)
         or _bundels(E_gr, int(.20 * min(H, Wd)), 10))
    if not G:
        return None
    g1, g2 = G
    off = max(7, int(.018 * min(H, Wd)))

    def vloerdeel(a, b, ctr):
        dv = (b - a) / max(np.linalg.norm(b - a), 1e-6)
        n = np.array([-dv[1], dv[0]])
        if n @ (ctr - (a + b) / 2) > 0:
            n = -n
        ok = c = 0
        for t in np.linspace(.08, .92, 40):
            p = a + (b - a) * t + n * off
            x, y = int(round(p[0])), int(round(p[1]))
            if not (0 <= x < Wd and 0 <= y < H):
                continue
            c += 1
            if np.linalg.norm(ab[y, x] - med) < tol:
                ok += 1
        return ok / c if c > 10 else .5

    def randsteun(a, b):
        k = 0
        for t in np.linspace(.05, .95, 50):
            p = a + (b - a) * t
            x, y = int(round(p[0])), int(round(p[1]))
            if 0 <= x < Wd and 0 <= y < H and sup[y, x]:
                k += 1
        return k / 50

    beste, bs = None, -9
    for a1, a2 in itertools.combinations(g1, 2):
        for b1, b2 in itertools.combinations(g2, 2):
            P = [_snijpunt(a1, b1), _snijpunt(b1, a2), _snijpunt(a2, b2), _snijpunt(b2, a1)]
            if any(p is None for p in P):
                continue
            q = order(P)
            if (q.min() < -.06 * max(H, Wd) or q[:, 0].max() > 1.06 * Wd
                    or q[:, 1].max() > 1.06 * H):
                continue
            opp = cv2.contourArea(q)
            if not (.10 * opp_foto < opp < .97 * opp_foto):
                continue
            zd = [np.linalg.norm(q[i] - q[(i + 1) % 4]) for i in range(4)]
            if min(zd) < 20:
                continue
            if abs(zd[0] - zd[2]) / max(zd) > .14 or abs(zd[1] - zd[3]) / max(zd) > .14:
                continue
            r = ((zd[0] + zd[2]) / 2) / ((zd[1] + zd[3]) / 2)
            if ratios and not any(abs(r - t) <= RTOL.get(t, rtol) * t for t in ratios):
                continue
            ctr = q.mean(0)
            es = [randsteun(q[i], q[(i + 1) % 4]) for i in range(4)]
            bf = [vloerdeel(q[i], q[(i + 1) % 4], ctr) for i in range(4)]
            sc = (.28 * np.mean(es) + .17 * min(es) + .32 * np.mean(bf)
                  + .15 * min(bf) + .08 * (opp / opp_foto))
            if sc > bs:
                bs, beste = sc, q
    return None if beste is None else (order(beste) / s, bs)


def autolevel(img):
    """Iets meer contrast, zodat kleine druk op een vale hoes leesbaar wordt."""
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    l = cv2.createCLAHE(clipLimit=1.6, tileGridSize=(8, 8)).apply(l)
    return cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)


# ---------- meetlat ----------------------------------------------------------

def order(p):
    p = np.asarray(p, "float32").reshape(4, 2)
    s, d = p.sum(1), np.diff(p, axis=1).ravel()
    return np.array([p[np.argmin(s)], p[np.argmin(d)],
                     p[np.argmax(s)], p[np.argmax(d)]], "float32")


def _zijden(q):
    return [float(np.linalg.norm(q[i] - q[(i + 1) % 4])) for i in range(4)]


def keur(q, ab, med, tol, vulling=1.0):
    """Cijfer tussen 0 en 1 voor een kandidaat, of None als hij onmogelijk is.

    Alle vier de randen worden apart bekeken en het MINIMUM telt zwaar mee. Een
    uitsnede die aan drie kanten klopt en aan de vierde dwars door de hoes loopt
    is geen driekwart goed, die is fout.
    """
    h, w = ab.shape[:2]
    opp_foto = h * w
    q = order(q)
    opp = float(cv2.contourArea(q))
    if not (.12 * opp_foto < opp < .98 * opp_foto):
        return None
    z = _zijden(q)
    if min(z) < 40:
        return None
    # overstaande zijden moeten ongeveer even lang zijn, anders is het geen
    # rechthoek maar een willekeurige vierhoek
    if abs(z[0] - z[2]) / max(z) > .16 or abs(z[1] - z[3]) / max(z) > .16:
        return None

    breed, hoog = (z[0] + z[2]) / 2, (z[1] + z[3]) / 2
    r = breed / hoog
    afw = min(abs(r - t) / t for t in VERHOUDINGEN)
    if afw > .14:
        return None
    vorm = 1.0 - afw / .14

    off = max(8, int(.022 * min(h, w)))
    mid = q.mean(0)
    buiten, binnen = [], []
    for i in range(4):
        a, b = q[i], q[(i + 1) % 4]
        d = (b - a) / max(np.linalg.norm(b - a), 1e-6)
        n = np.array([-d[1], d[0]])
        if n @ (mid - (a + b) / 2) > 0:
            n = -n                                   # n wijst naar buiten
        bu = bi = 0
        for t in np.linspace(.06, .94, 34):
            p = a + (b - a) * t
            pu, pi = p + n * off, p - n * off
            bu += is_vloer(ab, med, tol, int(round(pu[0])), int(round(pu[1])))
            bi += (not is_vloer(ab, med, tol, int(round(pi[0])), int(round(pi[1]))))
        buiten.append(bu / 34.0)
        binnen.append(bi / 34.0)

    return (.30 * float(np.mean(buiten)) + .25 * min(buiten) +
            .15 * float(np.mean(binnen)) + .10 * min(binnen) +
            .14 * vorm + .06 * vulling)


# ---------- kandidaten -------------------------------------------------------

def _quad_uit_masker(masker, opp_foto):
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    masker = cv2.morphologyEx(masker, cv2.MORPH_CLOSE, k, iterations=3)
    masker = cv2.morphologyEx(masker, cv2.MORPH_OPEN, k, iterations=2)
    cont, _ = cv2.findContours(masker, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cont:
        return None
    c = max(cont, key=cv2.contourArea)
    opp = cv2.contourArea(c)
    if opp < .10 * opp_foto:
        return None
    rect = cv2.minAreaRect(c)
    rechthoek_opp = max(rect[1][0] * rect[1][1], 1.0)
    return order(cv2.boxPoints(rect).astype("float32")), float(opp / rechthoek_opp)


def _op_drempel(g, opp, p):
    m = (g > np.percentile(g, p)).astype(np.uint8) * 255
    r = _quad_uit_masker(m, opp)
    return (r[0], r[1], f"p{p}") if r else None


def kandidaten(sm, ab, med, tol, ruim=False):
    """Lever vierhoeken op, uit verschillende invalshoeken.

    Niet om er zeker een goede tussen te hebben - dat zou willekeur zijn - maar
    omdat de meetlat pas kan kiezen als er iets te kiezen valt. Een enkele
    methode heeft geen concurrentie en wint dus altijd, ook als hij fout zit.

    In twee ronden. Gemeten over 60 foto's wint de lijndetectie er 35 en de
    goedkope drempels de rest; grabcut wint er drie. Grabcut is tegelijk de
    duurste stap die er is, dus die altijd draaien is vier keer betalen voor
    een keer resultaat. Met `ruim` komt hij er alsnog bij, en dat gebeurt
    precies wanneer de eerste ronde niets overtuigends oplevert - dan is hij
    zijn geld waard, want op die ene foto scheelde hij 0,20 punt.
    """
    h, w = sm.shape[:2]
    opp = h * w
    uit = []
    afst = np.linalg.norm(ab - med, axis=2)
    g = np.clip(afst / max(afst.max(), 1e-6) * 255, 0, 255).astype(np.uint8)

    if not ruim:
        # 1. de rand tussen vloerkleur en hoes, op een paar drempels. Otsu zoekt
        #    die zelf, maar gaat de mist in als de hoes twee sterk verschillende
        #    helften heeft: dan legt hij de grens middenin de hoes. Vandaar ook
        #    twee vaste percentielen ernaast.
        r = _quad_uit_masker(cv2.threshold(g, 0, 255,
                                           cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1], opp)
        if r:
            uit.append((r[0], r[1], "otsu"))
        for p in (45, 55):
            r = _op_drempel(g, opp, p)
            if r:
                uit.append(r)

        # 2. de lijndetectie uit v1, nu als gewone kandidaat zonder voorrang.
        #    Wel met de verhoudingen mee: zonder die filter loopt hij alle paren
        #    horizontale maal alle paren verticale lijnen af - ruim vierduizend
        #    vierhoeken - en meet hij van elk de vier randen na. De fout van de
        #    oude versie zat niet in het filteren maar in WAT er gefilterd werd:
        #    1:2 hoorde er ook bij.
        try:
            r = detect(sm, ratios=VERHOUDINGEN)
            if r is not None:
                uit.append((order(r[0]), 1.0, "lijnen"))
        except Exception:
            pass
        return uit

    # ruime ronde: strengere drempels en grabcut, dat begint met "de rand is
    # vloer, het midden is hoes" en dat zelf bijstelt. Dat is wat overblijft
    # als de hoes bijna dezelfde kleur heeft als de vloer en geen enkele
    # drempel de twee nog uit elkaar houdt.
    for p in (65, 75):
        r = _op_drempel(g, opp, p)
        if r:
            uit.append(r)
    try:
        f = 420.0 / max(h, w)
        mini = cv2.resize(sm, (int(w * f), int(h * f)), interpolation=cv2.INTER_AREA)
        mh, mw = mini.shape[:2]
        gc = np.zeros((mh, mw), np.uint8)
        rand = int(min(mh, mw) * .06)
        cv2.grabCut(mini, gc, (rand, rand, mw - 2 * rand, mh - 2 * rand),
                    np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64),
                    3, cv2.GC_INIT_WITH_RECT)
        m = np.where((gc == cv2.GC_FGD) | (gc == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
        r = _quad_uit_masker(cv2.resize(m, (w, h), interpolation=cv2.INTER_NEAREST), opp)
        if r:
            uit.append((r[0], r[1], "grabcut"))
    except cv2.error:
        pass
    return uit


def _lijnen(q):
    """Vierhoek als vier lijnen (steunpunt, richting), met de normaal naar buiten."""
    mid = q.mean(0)
    uit = []
    for i in range(4):
        a, b = q[i], q[(i + 1) % 4]
        d = (b - a) / max(np.linalg.norm(b - a), 1e-6)
        n = np.array([-d[1], d[0]])
        if n @ (mid - (a + b) / 2) > 0:
            n = -n
        uit.append((a.astype(np.float64), d, n, float(np.linalg.norm(b - a))))
    return uit


def _kruis(l1, l2):
    (a1, d1, _, _), (a2, d2, _, _) = l1, l2
    A = np.array([d1, -d2]).T
    if abs(np.linalg.det(A)) < 1e-9:
        return None
    t = np.linalg.solve(A, a2 - a1)
    return a1 + d1 * t[0]


def verfijn(q, ab, med, tol):
    """Elke rand los naar de echte overgang schuiven.

    Een masker levert zelden precies de buitenrand: morfologie eet er wat af of
    plakt er wat bij, en de minAreaRect eromheen rekt op naar de verste uitloper.
    Vandaar dat een uitsnede "net iets te ruim" of "net iets te krap" bleef, met
    een reepje vloer langs een kant.

    Dus wordt elke rand apart verschoven en gemeten met dezelfde meetlat als
    hiervoor: buiten moet vloer zijn, binnen niet. Die som heeft een piek op de
    echte rand - schuif je naar buiten, dan komt er vloer aan de binnenkant bij;
    schuif je naar binnen, dan verdwijnt de vloer aan de buitenkant. Zo hoeft
    het masker alleen ongeveer goed te zijn.
    """
    h, w = ab.shape[:2]
    off = max(6, int(.016 * min(h, w)))
    reik = max(8, int(.040 * min(h, w)))
    lijnen = _lijnen(order(q))
    nieuw = []
    for a, d, n, L in lijnen:
        beste, bd = -1.0, 0.0
        for verz in np.linspace(-reik, reik, 17):
            bu = bi = 0
            for t in np.linspace(.06, .94, 26):
                p = a + d * (t * L) + n * verz
                pu, pi = p + n * off, p - n * off
                bu += is_vloer(ab, med, tol, int(round(pu[0])), int(round(pu[1])))
                bi += (not is_vloer(ab, med, tol, int(round(pi[0])), int(round(pi[1]))))
            s = (bu + bi) / 52.0
            # gelijkspel gaat naar niet verschuiven: zonder bewijs blijft de
            # rand waar het masker hem legde
            if s > beste + 1e-9 or (abs(s - beste) < 1e-9 and abs(verz) < abs(bd)):
                beste, bd = s, float(verz)
        nieuw.append((a + n * bd, d, n, L))

    hoeken = [_kruis(nieuw[i], nieuw[(i + 1) % 4]) for i in range(4)]
    if any(p is None for p in hoeken):
        return q
    return order(np.array(hoeken, "float32"))


def zoek(img):
    """Beste vierhoek in de foto, in oorspronkelijke pixels. None als niets deugt."""
    h, w = img.shape[:2]
    s = KLEIN / float(w)
    sm = cv2.resize(img, (KLEIN, int(h * s)), interpolation=cv2.INTER_AREA)
    ab, med, tol = vloer_model(sm)
    beste, cijfer, bron = None, -1.0, None
    for ruim in (False, True):
        for q, vul, naam in kandidaten(sm, ab, med, tol, ruim):
            c = keur(q, ab, med, tol, vul)
            if c is not None and c > cijfer:
                beste, cijfer, bron = q, c, naam
        if cijfer >= GOED_GENOEG:
            break
    if beste is None:
        return None
    # bijschaven, maar alleen als de meetlat het er echt beter op vindt worden
    fijn = verfijn(beste, ab, med, tol)
    c = keur(fijn, ab, med, tol)
    if c is not None and c > cijfer:
        beste, cijfer = fijn, c
    return order(beste / s), cijfer, bron


# ---------- rechtop zetten ---------------------------------------------------
#
# Vier standen, maar het is geen keuze uit vier. Het zijn twee onafhankelijke
# vragen, en voor elk is er een goedkoop en eerlijk signaal:
#
#   kwartslag?   Staat de tekst op zijn kant? Dat is aan de VORM van de
#                tekstvakken te zien, niet aan de inhoud. "LADY IN BLUE" is
#                liggend een brede streep en staand een smalle. Daar is geen
#                letterherkenning voor nodig, alleen de detectiestap.
#   ondersteboven?  Precies waar het hoekmodel van RapidOCR voor gemaakt is:
#                het kijkt naar een uitgesneden tekstregel en zegt 0 of 180.
#
# De oude versie las in alle vier de standen de hele hoes en vergeleek het
# aantal woorden. Dat is vier keer het dure werk voor een antwoord dat uit ruis
# kwam - bij een hoes met weinig tekst leest de OCR ondersteboven net zo goed
# tien brokstukken als rechtop.
#
# Omdat het hoekmodel 0 tegen 180 afhandelt, hoeft de kwartslag niet te weten
# WELKE kant op. Een kwartslag de verkeerde kant op komt er ondersteboven uit,
# en dat wordt in de volgende stap alsnog rechtgezet.

MOTOR = None


def _een_draad_per_sessie():
    """Dwing onnxruntime af om één kern per proces te gebruiken.

    Dit moest, en het moest zo. `RapidOCR(intra_op_num_threads=1)` deed NIETS:
    de kwargs worden verdeeld over vier groepen op hun voorvoegsel - det_, cls_,
    rec_, en al het overige belandt in `Global`. Daar worden alleen text_score
    en soortgelijke uit gelezen. En `OrtInferSession` maakt zijn eigen
    SessionOptions aan en zet het aantal draden nergens, dus er is ook geen
    sleutel die het wel zou bereiken.

    Zonder deze ingreep valt onnxruntime terug op zijn standaard: alle kernen,
    per sessie, en RapidOCR opent er drie (detectie, hoek, herkenning). Gemeten
    op deze pc: 46 draden per proces. Met zes werkers zijn dat 276 draden op 20
    kernen, en de draadpoel van onnxruntime wacht al draaiend, dus die draden
    verbranden kernen terwijl ze op elkaar staan te wachten. Een volle keten
    haalde zo 6 foto's in 18 minuten terwijl alle 20 kernen bezet waren.

    Gemeten na deze ingreep: 7 draden per proces.

    Zo blijft het rekenwerk binnen een proces, en dat is precies wat je wil als
    je zelf al een proces per kern draait.
    """
    from rapidocr_onnxruntime import utils as ru
    if getattr(ru, "_draden_vastgezet", False):
        return
    echt = ru.SessionOptions

    def opties():
        o = echt()
        o.intra_op_num_threads = 1
        o.inter_op_num_threads = 1
        return o

    ru.SessionOptions = opties
    ru._draden_vastgezet = True


def motor():
    global MOTOR
    if MOTOR is None:
        cv2.setNumThreads(1)
        _een_draad_per_sessie()
        from rapidocr_onnxruntime import RapidOCR
        MOTOR = RapidOCR()
    return MOTOR


def _vakvormen(img):
    """Breedte/hoogte van elk gevonden tekstvak. Alleen detectie, geen lezen."""
    try:
        dozen, _ = motor().text_detector(img)
    except Exception:
        return [], []
    if dozen is None:
        return [], []
    vormen = []
    for d in dozen:
        xs, ys = d[:, 0], d[:, 1]
        vormen.append(float(xs.max() - xs.min()) / max(float(ys.max() - ys.min()), 1.0))
    return vormen, dozen


def _snij_regels(img, dozen, maxaantal=12):
    uit = []
    h, w = img.shape[:2]
    for d in sorted(dozen, key=lambda d: -(d[:, 0].max() - d[:, 0].min()))[:maxaantal]:
        x0, x1 = int(max(0, d[:, 0].min())), int(min(w, d[:, 0].max()))
        y0, y1 = int(max(0, d[:, 1].min())), int(min(h, d[:, 1].max()))
        if x1 - x0 > 12 and y1 - y0 > 6:
            uit.append(img[y0:y1, x0:x1])
    return uit


def rechtop(hoes, werkbreedte=1100):
    """Zet de hoes rechtop. Geeft (beeld, stand, reden, zeker) terug.

    Stand is "0", "90cw", "90ccw" of "180". `zeker` zegt of de kop-staartvraag
    echt beantwoord is of dat de hoes alleen maar is blijven liggen zoals hij
    lag. Dat verschil moet naar buiten: een hoes zonder een letter tekst is
    niet fout gedraaid, hij is niet te bepalen, en dat is iets om te melden in
    plaats van als antwoord te verkopen.
    """
    f = werkbreedte / max(hoes.shape[:2])
    klein = cv2.resize(hoes, None, fx=f, fy=f, interpolation=cv2.INTER_AREA) if f < 1 else hoes

    h, w = klein.shape[:2]
    vormen, dozen = _vakvormen(klein)

    # Een opengeklapte hoes is rechtop altijd breder dan hoog. Staat hij
    # rechtop in het beeld, dan moet hij een kwartslag - dat is zeker, ook
    # zonder een letter tekst.
    if h > w * 1.6:
        kwart, reden = True, "gatefold staat rechtop"
    elif w > h * 1.6:
        kwart, reden = False, "gatefold ligt al goed"
    elif not vormen:
        return hoes, "0", "geen tekst gevonden; niet te bepalen", False
    else:
        # Het AANDEEL liggende vakken, niet de mediaan van de verhouding. Die
        # verhouding is scheef verdeeld - een lange regel haalt 8, een staande
        # komt niet onder 0,12 - dus een mediaan van 0,88 zegt niet "bijna
        # liggend" maar "de helft ligt en de helft staat", en dat is geen
        # antwoord. Tellen hoeveel er liggen is wel een antwoord.
        deel = sum(1 for v in vormen if v > 1.0) / len(vormen)
        if len(vormen) < 3 or .35 < deel < .65:
            return hoes, "0", (f"tekstvakken wijzen niet één kant op "
                               f"({sum(1 for v in vormen if v > 1.0)}/{len(vormen)} liggend); "
                               f"niet te bepalen"), False
        kwart = deel <= .35
        reden = (f"{sum(1 for v in vormen if v > 1.0)}/{len(vormen)} tekstvakken liggend"
                 + (" dus een kwartslag" if kwart else ""))

    beeld = cv2.rotate(hoes, cv2.ROTATE_90_CLOCKWISE) if kwart else hoes
    stand = "90cw" if kwart else "0"
    if kwart:
        # alleen na een kwartslag moeten de vakken opnieuw gezocht worden; zonder
        # kwartslag zijn het nog dezelfde, en dat scheelt een detectieronde
        klein = cv2.rotate(klein, cv2.ROTATE_90_CLOCKWISE)
        _, dozen = _vakvormen(klein)

    # Nu liggen de regels horizontaal. Staan ze ook goed om te lezen?
    regels = _snij_regels(klein, dozen) if dozen is not None and len(dozen) else []
    zeker = False
    if regels:
        try:
            _, uitslag, _ = motor().text_cls(regels)
            om = sum(1 for lab, sc in uitslag if str(lab) == "180" and float(sc) > .7)
            n = sum(1 for lab, sc in uitslag if float(sc) > .7)
            if n >= 2:
                zeker = True
                if om > n / 2:
                    beeld = cv2.rotate(beeld, cv2.ROTATE_180)
                    stand = {"0": "180", "90cw": "90ccw"}[stand]
                    reden += f"; {om}/{n} regels ondersteboven"
                else:
                    reden += f"; {n} regels stonden goed"
        except Exception:
            pass
    if not zeker:
        reden += "; kop en staart niet te bepalen"
    return beeld, stand, reden, zeker


def snijd(img, zijde=3200):
    """Hoes eruit halen en het perspectief rechttrekken."""
    r = zoek(img)
    if r is None:
        return None, 0.0, None
    q = r[0]
    wq = (np.linalg.norm(q[0] - q[1]) + np.linalg.norm(q[3] - q[2])) / 2
    hq = (np.linalg.norm(q[0] - q[3]) + np.linalg.norm(q[1] - q[2])) / 2
    # De langste zijde krijgt de volle resolutie, zodat een liggende gatefold
    # niet op 3200 breed wordt uitgerekt en een staande op 6400 hoog.
    if wq >= hq:
        W, H = zijde, max(1, int(round(zijde * hq / wq)))
    else:
        H, W = zijde, max(1, int(round(zijde * wq / hq)))
    dst = np.array([[0, 0], [W - 1, 0], [W - 1, H - 1], [0, H - 1]], "float32")
    return (cv2.warpPerspective(img, cv2.getPerspectiveTransform(q, dst), (W, H),
                                flags=cv2.INTER_CUBIC), r[1], r[2])
