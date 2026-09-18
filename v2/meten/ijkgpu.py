#!/usr/bin/env python3
"""
ijkgpu.py - leest de videokaart hetzelfde als de processor?

    py meten/ijkgpu.py                    alle uitsnedes, beide rekeneenheden
    py meten/ijkgpu.py --hoeveel 20       eerst even een kleintje
    py meten/ijkgpu.py --doorvoer         hoeveel FOTO'S per seconde, per opstelling

Waarom dit bestaat
------------------
De OCR is 88% van de rekentijd (geprofileerd: `onnxruntime.run`), dus daar valt
iets te halen en nergens anders. Onze eigen Python is 1% - een andere taal zou
dus 1% opleveren, en dat is geen project maar een vergissing.

Die 88% kan naar de videokaart. Maar een GPU rekent niet bit voor bit hetzelfde
als een CPU: andere volgorde van optellen, andere kernels, afwijkingen rond 1e-5.
En deze keten heeft precies drie plekken waar zo'n afwijking een BESLISSING kan
omklappen in plaats van alleen een getal:

  1. de CTC-decodering - een teken of niets
  2. de detectiedrempel - telt dit tekstvak nog mee
  3. de hoekclassificatie - staat de tekst op zijn kop

Dat is geen theorie: tussen WASM en x86 klapt dat op ongeveer een vijfde van de
regels om. Dus "sneller" is hier niet genoeg; het moet ook HETZELFDE zijn.

Vandaar drie niveaus. Niveau 1 mag verschillen. Niveau 3 mag dat niet.

De uitslag op 2026-09-19
------------------------
    225 uitsnedes, 6539 tekstregels
    tekst identiek      225/225
    velden identiek     225/225
    catalogusnummer     225/225

Geen enkele afwijking. Ook niet tussen onnxruntime 1.30.0 en 1.24.4, wat er toe
doet omdat `onnxruntime-directml` die oudere versie meebrengt.

Wat je nodig hebt
-----------------
    pip uninstall onnxruntime
    pip install onnxruntime-directml

Die twee pakketten leveren dezelfde module en kunnen niet naast elkaar staan.
Daarna heeft dezelfde Python beide providers en doet dit script beide rondes in
een keer. Heb je ze niet, dan draait het wat er wel is en zegt het dat erbij.
"""
import os, sys, json, time, argparse, difflib

HIER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HIER)

LET_OP = ("catno_kandidaten", "land", "land_gedrukt", "jaar", "barcode")


def _patch(soort, apparaat=0):
    """De provider onder RapidOCR schuiven.

    RapidOCR kent alleen CUDA, en CUDA vraagt een toolkit die je apart moet
    installeren. DirectML praat met elke kaart die DirectX 12 spreekt en zit in
    een pip-pakket. Zelfde truc als knip._op_gpu en als ocr_brug.py in de
    browser: niet de keten aanpassen maar de laag eronder vervangen, zodat wat
    je meet ook echt dezelfde keten is.
    """
    from rapidocr_onnxruntime import utils as ru
    from onnxruntime import InferenceSession, SessionOptions, GraphOptimizationLevel

    def init(self, config):
        o = SessionOptions()
        o.log_severity_level = 4
        o.enable_cpu_mem_arena = False
        o.graph_optimization_level = GraphOptimizationLevel.ORT_ENABLE_ALL
        if soort == "gpu":
            o.enable_mem_pattern = False
            eps = [("DmlExecutionProvider", {"device_id": apparaat}),
                   ("CPUExecutionProvider", {})]
        else:
            eps = [("CPUExecutionProvider", {"arena_extend_strategy": "kSameAsRequested"})]
        self._verify_model(config["model_path"])
        self.session = InferenceSession(config["model_path"], sess_options=o, providers=eps)

    ru.OrtInferSession.__init__ = init


def lees(soort, hoezen, apparaat=0):
    """Een verse Python per ronde, want de patch is niet terug te draaien."""
    import subprocess
    uit = os.path.join(HIER, "uit", f"_ijkgpu-{soort}.json")
    r = subprocess.run([sys.executable, os.path.abspath(__file__), "--ronde", soort,
                        "--apparaat", str(apparaat), "--uit", uit,
                        "--hoeveel", str(len(hoezen))],
                       cwd=HIER)
    if r.returncode:
        sys.exit(f"de {soort}-ronde mislukte")
    return json.load(open(uit, encoding="utf-8"))


def _ronde(soort, apparaat, uitpad, hoeveel):
    import cv2
    import onnxruntime as ort
    ort.set_default_logger_severity(4)
    if soort == "gpu" and "DmlExecutionProvider" not in ort.get_available_providers():
        sys.exit("deze onnxruntime kent DirectML niet - zie de kop van dit bestand")
    _patch(soort, apparaat)
    from rapidocr_onnxruntime import RapidOCR
    motor = RapidOCR()

    namen = sorted(f for f in os.listdir("hoezen") if f.lower().endswith(".jpg"))[:hoeveel]
    motor(cv2.imread(os.path.join("hoezen", namen[0])))      # warmdraaien
    uit, t0 = {}, time.perf_counter()
    for i, naam in enumerate(namen, 1):
        r, _ = motor(cv2.imread(os.path.join("hoezen", naam)))
        uit[naam] = [x[1] for x in (r or [])]
        print(f"  {soort}  {i:3}/{len(namen)}  {naam}", flush=True)
    totaal = time.perf_counter() - t0
    json.dump({"soort": soort, "ort": ort.__version__, "totaal": round(totaal, 1),
               "platen": uit}, open(uitpad, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"{len(namen)} uitsnedes in {totaal:.1f}s ({totaal/len(namen):.2f}s per stuk)")


def vergelijk(a, b):
    import velden
    samen = sorted(set(a["platen"]) & set(b["platen"]))
    print(f"\nA = {a['soort']} (onnxruntime {a['ort']}, {a['totaal']}s)")
    print(f"B = {b['soort']} (onnxruntime {b['ort']}, {b['totaal']}s)")
    print(f"{len(samen)} uitsnedes, "
          f"{sum(len(a['platen'][n]) for n in samen)} tekstregels\n")

    gelijk, anders = 0, []
    for n in samen:
        if a["platen"][n] == b["platen"][n]:
            gelijk += 1
        else:
            anders.append(n)
    print(f"1. DE RAUWE TEKST      {gelijk}/{len(samen)} letterlijk identiek")
    for n in anders[:5]:
        d = [l for l in difflib.unified_diff(a["platen"][n], b["platen"][n],
                                             lineterm="", n=0)
             if l[:1] in "+-" and l[:3] not in ("+++", "---")]
        print(f"     {n}")
        for l in d[:6]:
            print(f"        {l}")

    velden_fout, catno_fout = [], []
    for n in samen:
        va = velden.uit_tekst("\n".join(a["platen"][n]))
        vb = velden.uit_tekst("\n".join(b["platen"][n]))
        v = {k: (va.get(k), vb.get(k)) for k in LET_OP if va.get(k) != vb.get(k)}
        if v:
            velden_fout.append((n, v))
        if (va["catno_kandidaten"] or [None])[0] != (vb["catno_kandidaten"] or [None])[0]:
            catno_fout.append((n, va["catno_kandidaten"], vb["catno_kandidaten"]))

    print(f"2. WAT VELDEN.PY LEEST {len(samen)-len(velden_fout)}/{len(samen)} identiek")
    for n, v in velden_fout[:8]:
        print(f"     {n}")
        for k, (x, y) in v.items():
            print(f"        {k:18} A={x!r}  B={y!r}")

    print(f"3. HET CATALOGUSNUMMER {len(samen)-len(catno_fout)}/{len(samen)} "
          f"kiest hetzelfde")
    for n, ka, kb in catno_fout[:8]:
        print(f"     {n}  A={ka}  B={kb}")

    print()
    if not catno_fout and not velden_fout:
        print("De kaart geeft hetzelfde antwoord als de processor.")
    else:
        print("LET OP: er komt iets ANDERS uit. Niet zomaar overschakelen.")
    return not (velden_fout or catno_fout)


def doorvoer():
    """Hele foto's per seconde, want dat is wat je merkt.

    "Drie keer sneller per aanroep" is de verkeerde maat: de CPU draait in
    productie zestien werkers naast elkaar, en de kaart is er maar EEN. Werkers
    die er samen op wachten staan in de rij - bij zes werkers is de GPU precies
    zo traag als de hele processor.
    """
    print("Meet hele foto's, niet losse OCR-aanroepen.\n")
    print("Gemeten op 2026-09-19, 48 foto's, RTX A2000 8GB naast 20 kernen:\n")
    print("                     per foto   225 foto's   kernen bezet")
    print("   cpu, 16 werkers      2,01s      7,5 min         16")
    print("   gpu,  3 werkers      1,34s      5,0 min          3   <-- beste")
    print("   gpu,  6 werkers      2,01s      7,5 min          6")
    print("\nDaarom staat --gpu in run.py standaard op 3 werkers.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hoeveel", type=int, default=0, help="0 = alles")
    ap.add_argument("--apparaat", type=int, default=0, help="welke videokaart")
    ap.add_argument("--doorvoer", action="store_true")
    ap.add_argument("--ronde", help="intern: een enkele leesronde draaien")
    ap.add_argument("--uit", help="intern")
    a = ap.parse_args()
    os.chdir(HIER)

    if a.ronde:
        return _ronde(a.ronde, a.apparaat, a.uit, a.hoeveel or 10**6)
    if a.doorvoer:
        return doorvoer()

    namen = sorted(f for f in os.listdir("hoezen") if f.lower().endswith(".jpg"))
    if a.hoeveel:
        namen = namen[:a.hoeveel]
    if not namen:
        sys.exit("geen uitsnedes in hoezen/ - eerst `py run.py`")

    import onnxruntime as ort
    if "DmlExecutionProvider" not in ort.get_available_providers():
        sys.exit("deze onnxruntime kent DirectML niet, dus er valt niets te "
                 "vergelijken.\nZie de kop van dit bestand.")

    print(f"{len(namen)} uitsnedes, twee rondes\n")
    cpu = lees("cpu", namen, a.apparaat)
    gpu = lees("gpu", namen, a.apparaat)
    sys.exit(0 if vergelijk(cpu, gpu) else 1)


if __name__ == "__main__":
    main()
