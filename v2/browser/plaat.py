"""
plaat.py - een plaat verwerken in de browser, van foto's tot prijs.

Dit is de browserkant van wat `run.py` op de PC doet, maar voor EEN plaat in
plaats van een hele map. Dat verschil is geen versimpeling maar het ontwerp:
op een telefoon heb je geen map met tweehonderd foto's, je hebt een plaat in je
hand. En het herkennen kost in Pyodide ruim vier keer zoveel als op de PC
(7,3s tegen 1,5s per plaat), dus een run van tweehonderd zou daar sowieso geen
goed idee zijn.

Wat er NIET anders is: elke stap komt uit dezelfde bestanden als op de PC.
`foto._verwerk` snijdt en leest, `groep.maak_plaat` bouwt het record,
`match.herken` kiest de persing, `prijs.prijzen` zoekt de marktprijs. Er is
geen tweede implementatie van iets.

De hoezenmap doet ertoe
-----------------------
`foto._verwerk` schrijft de uitgesneden, rechtgezette hoes naar `hoezendir`, en
`match.herken` leest hem daar weer op om hem naast de hoes op Discogs te
leggen. Die beeldronde is geen extraatje: hij ving vijf van de 97 platen af
waar de tekst naar de verkeerde persing wees, waaronder een dubbel-LP waar een
7"-single in de hoes zat.

In de browser is die map het geheugenbestandssysteem van Pyodide. Hij overleeft
het tabblad niet, en dat hoeft ook niet - de uitsnede wordt per plaat gemaakt
en meteen gebruikt. Wat je wilt bewaren gaat als JPEG terug naar de JS-kant.

Leesresolutie
-------------
`leespx` staat standaard op 1800 en niet op 3200 zoals op de PC. Dat is geen
smaak maar geheugen: de detectie schaalt niet terug (limit_type "min"), dus
3200x3200 is een invoer-tensor van 123 MB en die past niet in de brug naar
onnxruntime-web - laat staan in een telefoon.

Dat kost iets. Gemeten op de PC: 6,8s op 1200 pixels tegen 10,4s op 3200, maar
op volle resolutie werd "R. / BANK / DANR" wel "Gilbert O'Sullivan / HIMSELF /
MAM-SS501". `foto._verwerk` leest daarom eerst op 1800 en alleen bij weinig
woorden nog eens op `leespx`. Zet je `leespx` hoger, dan moet de brug mee.
"""
import os, json, time


def _schoon(naam):
    """Een bestandsnaam waar geen pad in kan verstoppen.

    De naam komt van een telefoon en dus van buiten. In Pyodide is het
    bestandssysteem wegwerpbaar, maar "../" in een naam zou nog steeds naar
    plekken kunnen schrijven waar de keten dingen verwacht.
    """
    naam = os.path.basename(str(naam or "")).replace("\\", "_")
    return "".join(c for c in naam if c.isalnum() or c in "._-")[:80] or "foto.jpg"


def verwerk(fotopaden, dc, werkmap="/werk", zijde=2400, leespx=1800,
            prijzen=True, melden=None, herkomst=""):
    """Foto's van EEN plaat -> een rij die de kast in kan.

    `fotopaden` is [(pad, naam), ...] met de voorkant eerst. Terug komt een
    dict met de plaat, de reden als het niet lukte, en de uitgesneden hoezen
    als JPEG-bytes zodat de JS-kant ze kan bewaren.
    """
    import cv2, foto, match, beeld
    from groep import maak_plaat

    # i.discogs.com stuurt geen Access-Control-Allow-Origin, dus een fetch
    # daarheen wordt door de browser geweigerd. Zonder omweg valt daarmee de
    # BEELDRONDE weg, en dat is niet een extraatje: die ving vijf van de 97
    # platen af waar de tekst naar de verkeerde persing wees. Dus lopen de
    # hoesafbeeldingen via een pad op onze eigen herkomst; kast.py en
    # vercel.json sturen dat door. Alleen publieke hoesfoto's, geen van jouw
    # eigen beeld.
    #
    # Met de VOLLEDIGE herkomst erin, niet als "/hoesbeeld/": `requests` weigert
    # een URL zonder schema met MissingSchema, en `beeld.haal` vangt dat af met
    # een kale `except` - dus het mislukte geruisloos en de beeldronde was er
    # stilletjes niet meer.
    beeld.PROXY = (herkomst.rstrip("/") + "/hoesbeeld/") if herkomst else ""

    hoezendir = os.path.join(werkmap, "hoezen")
    os.makedirs(hoezendir, exist_ok=True)

    # Alles wat hier gemeld wordt komt op het scherm terecht. Dat is geen
    # opsmuk: een plaat kost in de browser tientallen seconden en zonder een
    # teken van leven is "traag" niet van "vastgelopen" te onderscheiden - ook
    # niet voor wie hem gebouwd heeft.
    zeg = melden or (lambda *a, **k: None)

    t0 = time.time()
    gelezen = []
    for i, (pad, naam) in enumerate(fotopaden):
        zeg("foto", n=i + 1, totaal=len(fotopaden), naam=naam)
        r = foto._verwerk(pad, hoezendir, zijde, leespx, False)
        if r.get("fout"):
            return {"ok": False, "reden": f"{naam}: {r['fout']}"}
        gelezen.append(r)
        # De uitsnede staat nu op schijf. Meteen doorgeven, zodat je de hoes
        # rechtop ziet verschijnen terwijl de volgende foto nog moet.
        zeg("hoes", n=i + 1, totaal=len(fotopaden), bestand=r["bestand"],
            regels=len(r.get("vakken") or []), gesneden=bool(r.get("gesneden")),
            rechtop=bool(r.get("rechtop")), seconden=round(time.time() - t0, 1))
    t_lezen = time.time() - t0

    rec = maak_plaat(gelezen)

    zeg("zoeken", catno=(rec.get("catno_kandidaten") or [])[:3],
        kop=(rec.get("koptekst") or [])[:2])
    t1 = time.time()
    plaat, reden = match.herken(dc, rec, hoezendir)
    t_zoeken = time.time() - t1

    # De uitsnedes terug naar de JS-kant. Niet het origineel: dat heeft de
    # browser al, en de uitsnede is wat je in de kast wilt zien.
    hoezen = []
    for r in gelezen:
        p = r.get("pad")
        if p and os.path.exists(p):
            hoezen.append({"bestand": r["bestand"],
                           "bytes": open(p, "rb").read(),
                           "gesneden": r.get("gesneden"),
                           "rechtop": r.get("rechtop")})

    uit = {"ok": bool(plaat), "reden": reden, "rec": rec, "hoezen": hoezen,
           "tijden": {"lezen": round(t_lezen, 1), "zoeken": round(t_zoeken, 1)}}
    if not plaat:
        zeg("onherkend", reden=reden)
        return uit

    zeg("gevonden", artiest=plaat.get("artist"), titel=plaat.get("title"),
        release=plaat.get("release_id_auto"), seconden=round(t_zoeken, 1))

    uit["plaat"] = plaat

    if not prijzen:
        return uit

    zeg("prijs")
    t2 = time.time()
    try:
        import prijs as prijsmod, exporteer
        from nauwkeurig import beoordeel

        rijen = prijsmod.prijzen([plaat], dc,
                                 os.path.join(werkmap, "lookup_cache.json"))
        if rijen:
            # Zelfde afbeelding als op de PC: `exporteer.naar_plaat` is precies
            # de functie die collectie.json bouwt, en `nauwkeurig.beoordeel`
            # precies het stempel dat het rapport telt. Hier iets eigens van
            # maken zou betekenen dat je kast op je telefoon andere velden
            # toont dan die op je pc.
            niveau, redenen = beoordeel(plaat, rec)
            uit["kastplaat"] = exporteer.naar_plaat(
                rijen[0], niveau, redenen, plaat.get("beeld_punten"))
            zeg("klaar", prijs=uit["kastplaat"].get("prijs"),
                oordeel=niveau, artiest=uit["kastplaat"].get("artiest"),
                titel=uit["kastplaat"].get("titel"))
    except Exception as e:
        # Geen prijs is vervelend; geen plaat is erger. De persing staat al
        # vast, dus dit mag de hele plaat niet laten sneuvelen. Wel de hele
        # traceback meesturen: een opgeslokte fout hier kostte me een uur
        # zoeken, want van buiten zag het eruit als "niet herkend".
        import traceback
        uit["prijsfout"] = traceback.format_exc()[-1200:]
        zeg("prijsfout", bericht=f"{type(e).__name__}: {e}")
    uit["tijden"]["prijs"] = round(time.time() - t2, 1)
    return uit
