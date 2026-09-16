#!/usr/bin/env python3
"""
crop_sleeves.py v2 - detecteert een platenhoes, corrigeert het perspectief,
snijdt bij op de juiste verhouding en zet de foto rechtop.

    pip install opencv-python numpy
    sudo apt install tesseract-ocr        # optioneel, voor --autorotate
    python3 crop_sleeves.py ./fotos ./bijgeknipt

Hoe het werkt
  1. Achtergrondmodel: mediaan van de a/b-kanalen (LAB) langs de beeldrand. De
     helderheid L blijft buiten beschouwing, dus schaduw naast de hoes telt nog
     steeds als achtergrond.
  2. Hough-lijnen op de RAND VAN DIE ACHTERGRONDKAART, niet op de grijswaarden.
     Daardoor levert de illustratie op de hoes zelf geen kandidaatlijnen op --
     dat was de reden dat een vorige versie op de binnenkader van de hoes
     uitkwam in plaats van op de buitenrand.
  3. Alle combinaties van 2 horizontale en 2 verticale lijnen worden gescoord op
     randdekking en op "buiten de lijn ligt achtergrondkleur". Beste wint.
  4. Verhouding wordt gecontroleerd tegen --ratios, standaard 1:1 (hoes) en
     2:1 (opengeklapte gatefold of boekje).

Opties
  --size 1600      hoogte van de uitvoer in pixels
  --ratios 1,2     toegestane breedte/hoogte-verhoudingen
  --inset 0.5      procent extra naar binnen snijden
  --autorotate     zet de foto rechtop via tesseract OSD
  --review         schrijft contactvel.jpg om alles in een oogopslag te keuren
"""
import os, sys, re, csv, io, glob, argparse, subprocess, tempfile, itertools
import cv2
import numpy as np

W = 900


# ---------- achtergrondmodel -------------------------------------------------

def _bg(sm):
    lab = cv2.cvtColor(cv2.bilateralFilter(sm, 9, 50, 50), cv2.COLOR_BGR2LAB).astype(np.float32)
    ab = lab[:, :, 1:]
    h, w = ab.shape[:2]
    m = int(.035 * min(h, w))
    bd = np.concatenate([ab[:m].reshape(-1, 2), ab[-m:].reshape(-1, 2),
                         ab[:, :m].reshape(-1, 2), ab[:, -m:].reshape(-1, 2)])
    med = np.median(bd, 0)
    tol = max(6., float(np.percentile(np.linalg.norm(bd - med, axis=1), 85)))
    return ab, med, tol


# ---------- lijnen -----------------------------------------------------------

def _line(s):
    x1, y1, x2, y2 = s
    d = np.array([x2 - x1, y2 - y1], float)
    L = np.linalg.norm(d)
    if L < 1:
        return None
    d /= L
    n = np.array([-d[1], d[0]])
    r = abs(float(n @ np.array([x1, y1])))
    return (np.arctan2(d[1], d[0]) % np.pi, r, np.array([x1, y1], float), d, L)


def _groups(edge, minlen, keep):
    segs = cv2.HoughLinesP(edge, 1, np.pi / 360, 70, minLineLength=minlen, maxLineGap=30)
    if segs is None:
        return None
    L = [x for x in (_line(s) for s in segs.reshape(-1, 4)) if x]
    if len(L) < 4:
        return None
    a = np.array([l[0] for l in L])
    w = np.array([l[4] for l in L])
    hh, _ = np.histogram(a, 180, (0, np.pi), weights=w)
    hh = np.convolve(np.r_[hh, hh, hh], np.ones(7) / 7, 'same')[180:360]
    a0 = np.argmax(hh) * np.pi / 180
    g1, g2 = [], []
    for l in L:
        d = abs(((l[0] - a0 + np.pi / 2) % np.pi) - np.pi / 2)
        if d < np.deg2rad(12):
            g1.append(l)
        elif abs(d - np.pi / 2) < np.deg2rad(12):
            g2.append(l)

    def mg(g):
        g = sorted(g, key=lambda x: x[1])
        o = []
        for l in g:
            if o and abs(l[1] - o[-1][1]) < 14:
                if l[4] > o[-1][4]:
                    o[-1] = l
            else:
                o.append(l)
        return sorted(o, key=lambda x: -x[4])[:keep]

    g1, g2 = mg(g1), mg(g2)
    return (g1, g2) if len(g1) >= 2 and len(g2) >= 2 else None


def _inter(a, b):
    A = np.array([a[3], -b[3]]).T
    if abs(np.linalg.det(A)) < 1e-8:
        return None
    t = np.linalg.solve(A, b[2] - a[2])
    return a[2] + a[3] * t[0]


def order(p):
    p = np.asarray(p, 'float32').reshape(4, 2)
    s, d = p.sum(1), np.diff(p, axis=1).ravel()
    return np.array([p[np.argmin(s)], p[np.argmin(d)],
                     p[np.argmax(s)], p[np.argmax(d)]], 'float32')


# ---------- detectie ---------------------------------------------------------

RTOL = {1.0: .12, 2.0: .07}     # gatefold strenger: 1.86-2.14, geen 1.8


def detect(img, ratios=(1.0, 2.0), rtol=.12):
    h, w = img.shape[:2]
    s = W / float(w)
    sm = cv2.resize(img, (W, int(h * s)), interpolation=cv2.INTER_AREA)
    H, Wd = sm.shape[:2]
    area = H * Wd
    ab, med, tol = _bg(sm)

    d = np.linalg.norm(ab - med, axis=2)
    d = cv2.normalize(d, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    d = cv2.GaussianBlur(cv2.morphologyEx(d, cv2.MORPH_CLOSE,
                                          np.ones((9, 9), np.uint8), iterations=2), (7, 7), 0)
    E_bg = cv2.Canny(d, 40, 120)
    gray = cv2.bilateralFilter(cv2.cvtColor(sm, cv2.COLOR_BGR2GRAY), 7, 60, 60)
    E_gr = cv2.Canny(gray, 30, 90)
    sup = cv2.dilate(cv2.bitwise_or(E_bg, E_gr), np.ones((3, 3), np.uint8), iterations=2)

    G = _groups(E_bg, int(.18 * min(H, Wd)), 12) or _groups(E_gr, int(.20 * min(H, Wd)), 10)
    if not G:
        return None
    g1, g2 = G
    off = max(7, int(.018 * min(H, Wd)))

    def bgfrac(a, b, ctr):
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

    def esup(a, b):
        n = 50
        k = 0
        for t in np.linspace(.05, .95, n):
            p = a + (b - a) * t
            x, y = int(round(p[0])), int(round(p[1]))
            if 0 <= x < Wd and 0 <= y < H and sup[y, x]:
                k += 1
        return k / n

    best, bs = None, -9
    for a1, a2 in itertools.combinations(g1, 2):
        for b1, b2 in itertools.combinations(g2, 2):
            P = [_inter(a1, b1), _inter(b1, a2), _inter(a2, b2), _inter(b2, a1)]
            if any(p is None for p in P):
                continue
            q = order(P)
            if q.min() < -.06 * max(H, Wd) or q[:, 0].max() > 1.06 * Wd or q[:, 1].max() > 1.06 * H:
                continue
            ar = cv2.contourArea(q)
            if not (.10 * area < ar < .97 * area):
                continue
            sd = [np.linalg.norm(q[i] - q[(i + 1) % 4]) for i in range(4)]
            if min(sd) < 20:
                continue
            if abs(sd[0] - sd[2]) / max(sd) > .14 or abs(sd[1] - sd[3]) / max(sd) > .14:
                continue
            breed, hoog = (sd[0] + sd[2]) / 2, (sd[1] + sd[3]) / 2
            r = breed / hoog
            # Een gatefold of boekjespagina ligt altijd breder dan hoog.
            # Zonder deze eis werd een staande 1:2 uitsnede ook aanvaard.
            if ratios and not any(abs(r - t) <= RTOL.get(t, rtol) * t for t in ratios):
                continue
            ctr = q.mean(0)
            es = [esup(q[i], q[(i + 1) % 4]) for i in range(4)]
            bf = [bgfrac(q[i], q[(i + 1) % 4], ctr) for i in range(4)]
            sc = .28 * np.mean(es) + .17 * min(es) + .32 * np.mean(bf) + .15 * min(bf) + .08 * (ar / area)
            if sc > bs:
                bs, best = sc, q
    return None if best is None else (order(best) / s, bs)


# ---------- uitvoer ----------------------------------------------------------

def _op_tijdstip(paden):
    """Sorteer op de cijfers in de bestandsnaam, niet alfabetisch.
    IMG_20260913_160652 en IMG20260913160630 komen van verschillende camera-apps;
    alfabetisch belandt de eerste achteraan en raken voor- en achterkant gescheiden."""
    def sleutel(f):
        d = re.sub(r"\D", "", os.path.basename(f))
        return (0, d.ljust(20, "0")) if len(d) >= 12 else (1, os.path.basename(f))
    return sorted(paden, key=sleutel)


def autolevel(img):
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    l = cv2.createCLAHE(clipLimit=1.6, tileGridSize=(8, 8)).apply(l)
    return cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)


TESS = "tesseract"          # wordt door --tesseract overschreven


def tess_check():
    """Controleert of tesseract werkt en of de OSD-data aanwezig is."""
    try:
        v = subprocess.run([TESS, "--version"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=20)
    except FileNotFoundError:
        return f"tesseract niet gevonden op: {TESS}"
    except Exception as e:
        return f"tesseract start niet: {e}"
    if v.returncode != 0:
        return "tesseract geeft een fout bij --version"
    langs = subprocess.run([TESS, "--list-langs"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=20)
    if "osd" not in (langs.stdout + langs.stderr):
        return ("osd.traineddata ontbreekt. Download osd.traineddata van "
                "github.com/tesseract-ocr/tessdata en zet het in de map tessdata "
                "naast tesseract.exe.")
    return None


def _ocr_score(img):
    """Som van de betrouwbaarheid van herkende woorden. Hoe beter de foto
    rechtop staat, hoe meer echte woorden tesseract eruit haalt."""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as t:
        cv2.imwrite(t.name, img)
    try:
        r = subprocess.run([TESS, t.name, "-", "-l", "eng", "--psm", "3", "tsv"],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=60)
    except Exception:
        return 0.0
    finally:
        try:
            os.unlink(t.name)
        except OSError:
            pass
    tot = 0.0
    for row in csv.DictReader(io.StringIO(r.stdout), delimiter="\t",
                              quoting=csv.QUOTE_NONE):
        try:
            c = float(row.get("conf", -1))
        except (TypeError, ValueError):
            continue
        w = (row.get("text") or "").strip()
        if c >= 60 and len(w) >= 3 and any(ch.isalpha() for ch in w):
            tot += c
    return tot


ROTS = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180,
        270: cv2.ROTATE_90_COUNTERCLOCKWISE}


def _osd(img):
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as t:
        cv2.imwrite(t.name, img)
    try:
        r = subprocess.run([TESS, t.name, "-", "--psm", "0"],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=30)
    except Exception:
        return 0, 0.0
    finally:
        try:
            os.unlink(t.name)
        except OSError:
            pass
    d = dict(l.split(":", 1) for l in r.stdout.splitlines() if ":" in l)
    try:
        return int(d.get("Rotate", "0").strip()), float(
            d.get("Orientation confidence", "0").strip())
    except ValueError:
        return 0, 0.0


def bepaal_draaiing(img, report=None, name=""):
    """Drie signalen op volgorde van betrouwbaarheid.
    1. OSD van tesseract, maar alleen als die zichzelf zeker noemt.
    2. Woordenscore rechtop tegenover ondersteboven, met een duidelijke marge.
    3. Kwartslagen, enkel bij een zeer groot verschil, want daar haalt OCR ook
       uit ruis nog brokstukken.
    Is geen ervan beslissend, dan blijft de foto staan en gaat hij in de lijst."""
    f = 1000.0 / max(img.shape[:2])
    klein = cv2.resize(img, (int(img.shape[1] * f), int(img.shape[0] * f)),
                       interpolation=cv2.INTER_AREA) if f < 1 else img

    rot, conf = _osd(klein)
    if conf >= 2.0:
        return rot

    s0 = _ocr_score(klein)
    s180 = _ocr_score(cv2.rotate(klein, ROTS[180]))
    hoog, laag = max(s0, s180), min(s0, s180)

    if hoog >= 200 and hoog >= 1.6 * max(laag, 1):
        keuze = 0 if s0 >= s180 else 180
        s90 = _ocr_score(cv2.rotate(klein, ROTS[90]))
        s270 = _ocr_score(cv2.rotate(klein, ROTS[270]))
        if max(s90, s270) >= 2.0 * hoog:
            return 90 if s90 >= s270 else 270
        return keuze

    if report is not None:
        report.append(f"{name}  (te weinig leesbare tekst: "
                      f"rechtop {s0:.0f}, omgekeerd {s180:.0f}, OSD-zekerheid {conf:.2f})")
    return 0


def apply_rot(img, rot):
    m = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180,
         270: cv2.ROTATE_90_COUNTERCLOCKWISE}
    return cv2.rotate(img, m[rot]) if rot in m else img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("indir"); ap.add_argument("outdir")
    ap.add_argument("--size", type=int, default=1600)
    ap.add_argument("--ratios", default="1,2")
    ap.add_argument("--inset", type=float, default=0.0)
    ap.add_argument("--autorotate", action="store_true")
    ap.add_argument("--tesseract", default="tesseract",
                    help=r'pad naar tesseract.exe, bv. "C:\Program Files\Tesseract-OCR\tesseract.exe"')
    ap.add_argument("--no-level", action="store_true")
    ap.add_argument("--review", action="store_true")
    a = ap.parse_args()

    if a.autorotate:
        global TESS
        TESS = a.tesseract
        err = tess_check()
        if err:
            sys.exit("Rechtzetten kan niet: " + err)
        print("tesseract gevonden, OSD beschikbaar\n")

    ratios = tuple(float(x) for x in a.ratios.split(",") if x.strip())
    os.makedirs(a.outdir, exist_ok=True)
    # glob is hoofdletterongevoelig op Windows, dus *.jpg en *.JPG geven
    # dezelfde bestanden terug. Zonder dit wordt elke foto twee keer verwerkt.
    files = _op_tijdstip({os.path.normcase(f): f for f in
                    sum((glob.glob(os.path.join(a.indir, e))
                         for e in ("*.jpg", "*.jpeg", "*.JPG", "*.JPEG", "*.png")),
                        [])}.values())
    todo, thumbs, onzeker = [], [], []

    for f in files:
        img = cv2.imread(f)
        name = os.path.splitext(os.path.basename(f))[0]
        r = detect(img, ratios) if img is not None else None
        if r is None:
            print(f"HANDMATIG  {name}")
            todo.append(name)
            continue
        q, sc = r
        if a.inset:
            c = q.mean(0)
            q = (c + (q - c) * (1 - a.inset / 100.)).astype("float32")
        wq = (np.linalg.norm(q[0] - q[1]) + np.linalg.norm(q[3] - q[2])) / 2
        hq = (np.linalg.norm(q[0] - q[3]) + np.linalg.norm(q[1] - q[2])) / 2
        H = a.size
        Wo = int(round(H * wq / hq))
        dst = np.array([[0, 0], [Wo - 1, 0], [Wo - 1, H - 1], [0, H - 1]], "float32")
        out = cv2.warpPerspective(img, cv2.getPerspectiveTransform(q, dst),
                                  (Wo, H), flags=cv2.INTER_CUBIC)
        if a.autorotate:
            out = apply_rot(out, bepaal_draaiing(out, report=onzeker, name=name))
        if not a.no_level:
            out = autolevel(out)
        cv2.imwrite(os.path.join(a.outdir, name + ".jpg"), out,
                    [cv2.IMWRITE_JPEG_QUALITY, 92])
        print(f"OK  {sc:.2f}  {name}  ({Wo}x{H})")
        if a.review:
            # vaste tegel, foto erin gepast: anders lopen tegels van
            # verschillende breedte (vierkant vs gatefold) over elkaar heen
            TL = 300
            f = min(TL / out.shape[1], (TL - 22) / out.shape[0])
            small = cv2.resize(out, (max(1, int(out.shape[1] * f)),
                                     max(1, int(out.shape[0] * f))))
            tile = np.full((TL, TL, 3), 245, np.uint8)
            y0 = 22 + (TL - 22 - small.shape[0]) // 2
            x0 = (TL - small.shape[1]) // 2
            tile[y0:y0 + small.shape[0], x0:x0 + small.shape[1]] = small
            cv2.putText(tile, name[-10:], (6, 16), cv2.FONT_HERSHEY_SIMPLEX,
                        .45, (0, 0, 200), 1, cv2.LINE_AA)
            thumbs.append(tile)

    if a.review and thumbs:
        cols = 6
        while len(thumbs) % cols:
            thumbs.append(np.full((300, 300, 3), 255, np.uint8))
        rows = [np.hstack(thumbs[i:i + cols]) for i in range(0, len(thumbs), cols)]
        cv2.imwrite(os.path.join(a.outdir, "contactvel.jpg"), np.vstack(rows),
                    [cv2.IMWRITE_JPEG_QUALITY, 88])

    if todo:
        with open(os.path.join(a.outdir, "handmatig.txt"), "w") as fh:
            fh.write("\n".join(todo))
    if onzeker:
        with open(os.path.join(a.outdir, "rechtzetten.txt"), "w") as fh:
            fh.write("\n".join(onzeker))
    print(f"\n{len(files) - len(todo)} gelukt, {len(todo)} handmatig, "
          f"{len(onzeker)} onzeker rechtgezet (zie rechtzetten.txt)")


if __name__ == "__main__":
    main()
