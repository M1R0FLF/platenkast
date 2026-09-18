"""
ocr_brug.py - onnxruntime vervangen, en verder alles laten zoals het was.

Dit is het ENIGE bestand waarin de browserversie afwijkt van de PC-versie.
knip, foto, groep, velden, match, beeld en heel rapidocr_onnxruntime draaien
onveranderd; ze merken hier niets van.

Wat er vervangen wordt
----------------------
`rapidocr_onnxruntime.utils.OrtInferSession` doet twee dingen: een .onnx
inladen, en er tensors doorheen duwen. In de browser doet onnxruntime-web dat,
op een eigen draad. Wat hier overblijft is een klasse die er precies zo uitziet
voor wie hem gebruikt - `__call__`, `get_input_names`, `have_key`,
`get_character_list` - en die het rekenwerk over de draadgrens schuift.

Waarom er geen `await` in staat
-------------------------------
`TextDetector.__call__` is synchroon en dat blijft zo. De brug legt de tensor
in gedeeld geheugen, tikt de rekendraad aan en gaat op `Atomics.wait` staan.
Deze draad staat dan echt stil - geen bezige lus, geen kernen verbranden - tot
het antwoord er is. Voor Python is het een gewone functieaanroep die even
duurt, net als op de PC.

Waarom de tekenset apart meekomt
--------------------------------
De 6623 tekens staan in de metadata van het rec-model, en die metadata kan
onnxruntime-web niet uitlezen; er is geen API voor. `bundel.py` haalt ze er
daarom een keer uit met Python en zet ze ernaast als tekenset.txt. Zonder deze
lijst leest het model wel, maar komt er onzin uit: de index klopt dan met niets.
"""
import sys, types
import numpy as np
from pyodide.ffi import to_js
import js

# Wat de brug van de JS-kant verwacht. Wordt daar neergezet voor dit bestand
# geimporteerd wordt; ontbreekt het, dan moet dat hier knallen en niet later
# stilletjes een lege hoes opleveren.
for _naam in ("brugVraag", "brugInvoer", "brugUitvoer", "brugTekenset"):
    if not hasattr(js, _naam):
        raise RuntimeError(f"de JS-kant van de brug ontbreekt: {_naam}")


class Brugfout(RuntimeError):
    pass


def draai(naam, x):
    """Een tensor door een model, over de draadgrens.

    `naam` is "det", "rec" of "cls". Terug komt een numpy-array met de vorm
    die het model teruggaf - niet de vorm die wij verwachtten, want die twee
    uit elkaar houden is precies hoe je merkt dat er iets niet klopt.
    """
    x = np.ascontiguousarray(x, dtype=np.float32)
    if x.nbytes > js.brugInvoer.byteLength:
        raise Brugfout(
            f"{naam}: invoer van {x.nbytes / 1e6:.1f} MB past niet in de "
            f"brug van {js.brugInvoer.byteLength / 1e6:.0f} MB. "
            f"Lees op een kleinere zijde.")

    js.brugInvoer.subarray(0, x.size).assign(x)     # memcpy, geen omweg
    antwoord = js.brugVraag(naam, to_js(list(x.shape)), int(x.size)).to_py()

    status, lengte = antwoord[0], antwoord[1]
    if status != 1:
        raise Brugfout(antwoord[2] if len(antwoord) > 2 else "onbekende fout")

    vorm = antwoord[2]
    uit = np.empty(lengte, dtype=np.float32)
    js.brugUitvoer.subarray(0, lengte).assign_to(uit)
    return uit.reshape(vorm)


class OrtInferSession:
    """Dezelfde vorm als het origineel, andere motor eronder."""

    def __init__(self, config):
        pad = str(config.get("model_path", ""))
        if "_det_" in pad:
            self.naam = "det"
        elif "_rec_" in pad:
            self.naam = "rec"
        elif "cls" in pad:
            self.naam = "cls"
        else:
            raise Brugfout(f"onbekend model: {pad}")

    def __call__(self, invoer):
        # Het origineel geeft een LIJST terug (session.run levert alle
        # uitvoeren), en de aanroepers pakken er [0] uit. Die vorm houden we
        # aan, anders breken ze.
        return [draai(self.naam, invoer)]

    def get_input_names(self):
        return ["x"]

    def get_output_names(self):
        return ["uit"]

    def get_character_list(self, key="character"):
        return js.brugTekenset.splitlines()

    def have_key(self, key="character"):
        return self.naam == "rec"


def _nep_onnxruntime():
    """Een onnxruntime die alleen bestaat om de import te laten slagen.

    `rapidocr_onnxruntime.utils` haalt vijf namen binnen op moduleniveau. Geen
    ervan wordt nog gebruikt zodra OrtInferSession vervangen is, maar zonder
    ze klapt de import eruit voor we daaraan toe komen.
    """
    m = types.ModuleType("onnxruntime")

    class _Opties:
        pass

    class _Niveau:
        ORT_ENABLE_ALL = 99

    def _weg(*a, **k):
        raise Brugfout("onnxruntime draait hier niet; de brug hoort dit af te "
                       "vangen. Is OrtInferSession wel vervangen?")

    m.SessionOptions = _Opties
    m.GraphOptimizationLevel = _Niveau
    m.InferenceSession = _weg
    m.get_available_providers = lambda: []
    m.get_device = lambda: "CPU"
    return m


def installeer():
    """Zet de brug op zijn plaats. Moet voor `import rapidocr_onnxruntime`.

    Geeft terug welke klasse er nu in utils staat, zodat de aanroeper kan
    controleren dat het echt de onze is in plaats van te hopen.
    """
    sys.modules.setdefault("onnxruntime", _nep_onnxruntime())

    import rapidocr_onnxruntime.utils as ru
    ru.OrtInferSession = OrtInferSession

    # De submodules doen `from rapidocr_onnxruntime.utils import
    # OrtInferSession` en binden dus op IMPORT-moment. RapidOCR laadt ze pas
    # bij het aanmaken, via importlib - dus dit is op tijd. Maar als er al een
    # geladen is (tweede aanroep), moet die ook om.
    for mod in list(sys.modules.values()):
        if getattr(mod, "__name__", "").startswith("rapidocr_onnxruntime."):
            if hasattr(mod, "OrtInferSession"):
                mod.OrtInferSession = OrtInferSession

    return ru.OrtInferSession
