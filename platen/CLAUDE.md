# Platenverkoop

## Stand van zaken

225 foto's -> **100 platen** -> **98 herkend (98%)**, 2 te gaan.
`uitvoer/platen.csv` bevat die 98, waarvan 87 met een marktprijs, samen EUR 499.

De oude keten deed 24 van 134 (18%), allemaal LP en geen enkele single.

| stap | erbij |
|---|---|
| RapidOCR in plaats van tesseract, groeperen op gedeelde tekst | 24 -> 54 |
| singles niet meer afwijzen op een eis die ze niet konden halen | -> 72 |
| titel+label+catalogusnummer als tweede verificatieweg | -> 79 |
| de rest opnieuw lezen van de ORIGINELE foto's (3200px) | -> 86 |
| herkennen aan de hoesafbeelding | -> 95 |
| opengeklapte hoezen en eenlingen goed groeperen | -> 98 |

Wat nog ligt: een naamloze Franse EP (17.335) en een Belgische Decca-single
(26.225). Allebei nauwelijks tekst en niet op Discogs te vinden.

Een volledige herberekening duurt ongeveer twee minuten. Stond eerst op tien:
`automatch.py` haalde van elke kandidaat de tracklist op, terwijl het
zoekresultaat zelf al titel, catalogusnummer, land en aantal bezitters
meestuurt. Nu wordt daar eerst goedkoop op gerangschikt en worden alleen de
twaalf besten opgehaald.

## De volgorde van de foto's

Miro fotografeert **altijd** voorkant, dan achterkant, en wat daarna komt is de
binnenkant. Dat staat vast en de keten leunt erop:

- de eerste foto van een groep is de voorkant, de tweede de achterkant
- een plaat met maar één foto bestaat niet; dat is altijd een verkeerde knip
- een opengeklapte hoes is breder dan hoog (17 van de 225 foto's) en hoort
  altijd bij de plaat ervoor, nooit bij een nieuwe

## Controleren

`py controleer.py` zoekt verdachte matches: een persing uit een land waar hier
niets vandaan komt, label "Not On Label", een catalogusnummer dat niet op de
hoes terug te vinden is, of een single met twaalf nummers. Dat vindt geen
fouten met zekerheid, het wijst aan wat een blik waard is. Nu: 16 opmerkingen
op 79 platen, waarvan de meeste alleen "geen jaar".

### Waar de tijd in gaat

Niet in je PC. Het OCR-deel is rekenwerk en draait parallel, maar dat is
eenmalig en staat in `ocr2_cache.json`. Het matchen hangt volledig aan Discogs,
en dat mag met een token 60 aanroepen per minuut. Meer kernen helpen daar
niets. Wat wel helpt is minder aanroepen doen, en dat is waar
`discogs_cache.json` voor is: een tweede ronde kost bijna niks meer.


Van foto's van platenhoezen naar een CSV met Discogs-match, marktprijs en
advertentietekst, klaar voor 2dehands.

## De keten

Alles tot en met stap 3 draait lokaal op de PC en kost niets. Jij komt pas in
stap 4, en alleen voor wat er dan nog overblijft.

| stap | script | wat |
|---|---|---|
| 1 | `crop_sleeves.py` | hoes uitsnijden, rechtzetten |
| 2 | `leesfotos.py` | RapidOCR over elke foto apart, naar `ocr2_cache.json` |
| 3 | `groepeer.py` | foto's per plaat groeperen, velden uit de tekst, naar `ruw2.json` |
| 4 | `automatch.py` | Discogs-match die zichzelf verifieert tegen de tracklist |
| 5 | `herlees.py` | de rest opnieuw lezen van de ORIGINELE foto's, op 3200px |
| 6 | `beeldmatch.py` | wat dan nog rest herkennen aan de hoesafbeelding |
| 7 | **jij** | alleen wat in `voor_claude.json` overblijft |
| 8 | `lookup.py` | marktprijs en advertentietekst voor alles samen |

Hulpstukken: `controleer.py` (verdachte matches opsporen), `opschonen.py`
(platen.json weer in de pas brengen na een nieuwe groepering), `voortgang.py`
(stand van zaken), `hints.json` (zoekhints voor `beeldmatch.py`).

Stap 1 tot 4 starten met `.\run.ps1`. Die is herstartbaar en slaat over wat al
gedaan is. Stap 2 duurt ongeveer drie kwartier voor 225 foto's, maar hoeft maar
één keer.

`prep.py` deed stap 2 en 3 vroeger in één keer met tesseract. Dat werkt niet:
tesseract las 27% van de foto's op nul tekens, en het groeperen hing aan de
hoeveelheid tekst. Zie de kop van `groepeer.py` en `groepsignaal.py` voor de
metingen. `prep.py` levert nu alleen nog het uitlezen van velden
(`uit_tekst`) en het klaarzetten van de kit.

## Mappen

- `fotos/` — originelen van de gsm. Nooit wijzigen.
- `bijgeknipt/` — uitgesneden hoezen, plus `contactvel.jpg`, `handmatig.txt`, `rechtzetten.txt`
- `kit/` — verkleinde beelden voor als tekst niet volstaat
- `handmatig/` — hier zet Miro zelf bijgeknipte hoezen bij
- `uitvoer/` — `platen.csv`, het eindresultaat
- `ocr2_cache.json` — RapidOCR per foto. Duur om te maken, niet weggooien.
- `ruw2.json` — OCR en gevonden velden per plaat, uit `groepeer.py`
- `platen.json` — de definitieve lijst, gevuld door `automatch.py` en door jou
- `voor_claude.json` — wat automatisch niet lukte. Dit is jouw werklijst.

`ruw.json` is de oude uitvoer van `prep.py` en wordt niet meer gebruikt.

## Jouw taak

Werk `voor_claude.json` af en voeg de resultaten toe aan `platen.json`.

Dit zijn de moeilijke gevallen: donkere hoezen waar OCR niets van maakt, hoezen
zonder leesbaar catalogusnummer, en platen die niet op Discogs staan. Verwacht
geen makkelijke.

**Beeld is het dure stuk.** Probeer altijd eerst de tekst. Moet je toch kijken,
open dan in deze volgorde en stop zodra je genoeg hebt:

1. `beelden.hoek` — bovenste strook van de achterkant, volle scherpte. Daar staat
   het catalogusnummer bijna altijd. Ongeveer 300 tokens.
2. `beelden.voor` — kleine voorkant, genoeg voor artiest en titel. Ongeveer 480.
3. `beelden.achter` — de hele achterkant. Ongeveer 1000, dus enkel als laatste.

Elk item vermeldt bij `beelden` de geschatte kosten.

### Wat je invult

`catno_kandidaten` is een ruwe greep uit de OCR en zit vol ruis. Kies de juiste
of zet `null`. Nooit zelf een nummer verzinnen: een gegokt catalogusnummer levert
een match op de verkeerde persing en dat merkt niemand nog.

Het land van persing weegt zwaar. Zonder land kiest Discogs makkelijk de
Amerikaanse persing terwijl dit een Europese is, en die zijn anders geprijsd.

Soort drager:
- `LP` — vier of meer nummers per kant
- `EP` — een handvol nummers, vaak expliciet "EP"
- `single7` — één nummer per kant, vaak "45 RPM"
- `maxi12` — 12 inch met twee of drie nummers, vaak "Maxi" of "Extended"

Ruwweg de helft van deze verzameling bestaat uit singles. Die zien er in de OCR
heel anders uit dan een LP: geen tracklist, maar twee plaatlabels met elk
twintig tot zestig tekens. Herkenbaar aan hetzelfde catalogusnummer op beide
foto's, vaak met een A en een B erachter (`AA702A` / `AA702B`). Bij een single
vul je `a_kant` en `b_kant` in en is `aantal_nummers` twee.

Bij `staat_hoes` alleen wat je echt vaststelt. Geen beeld bekeken is `null`. Die
tekst gaat letterlijk de advertentie in, dus niets verfraaien en niets verzinnen.

Zet `"bron": "claude"` zodat achteraf te zien is wat automatisch ging.

### Formaat

`platen.json` is één lijst. Toevoegen, nooit iets weggooien.

```json
{
  "id": "160630",
  "fotos": ["IMG20260913160630.jpg", "IMG_20260913_160652.jpg"],
  "artist": "Gloria Gaynor",
  "title": "Never Can Say Goodbye",
  "label": "MGM Records",
  "catno": "2315 321",
  "barcode": null,
  "country": "Germany",
  "year": 1975,
  "soort": "LP",
  "lp_count": 1,
  "gatefold": false,
  "a_kant": null,
  "b_kant": null,
  "aantal_nummers": 8,
  "notes": "Printed in Germany by Gerhard Kaiser GmbH Essen",
  "staat_hoes": null,
  "bron": "claude"
}
```

`a_kant` en `b_kant` alleen bij een single of maxi.

### Werkwijze

Blokken van tien. Schrijf na elk blok weg naar `platen.json` en meld kort hoeveel
je puur uit tekst deed en bij hoeveel je beeld nodig had. Sla over wat al in
`platen.json` staat.

Kom je er bij een plaat niet uit, zet dan `artist` en `title` zo goed als je kan
en de rest op `null`. Een half ingevulde plaat is bruikbaar, een verzonnen niet.

## Daarna

```
py lookup.py platen.json uitvoer\platen.csv
```

Zoekt de persing op Discogs, haalt de marktdata op en schrijft de CSV met
vraagprijs, advies, titel en advertentietekst.

## Als iets stukloopt

Je mag de scripts aanpassen. Twee vallen die zich al voordeden:

- Op Windows decodeert Python de uitvoer van een extern programma standaard als
  cp1252 terwijl tesseract UTF-8 schrijft. Altijd `encoding="utf-8",
  errors="replace"` meegeven aan `subprocess.run`.
- `glob` is op Windows hoofdletterongevoelig, dus `*.jpg` en `*.JPG` geven
  dezelfde bestanden. Altijd ontdubbelen op `os.path.normcase`.

Bestandsnamen sorteren op de cijfers erin, niet alfabetisch. Er staan twee
naamstijlen door elkaar en alfabetisch belandt de ene stijl volledig achteraan.

## Niet doen

- Geen advertenties plaatsen op 2dehands. Die stap doet Miro zelf.
- Niets wijzigen in `fotos/`.
- Prijzen niet zelf schatten. Die komen uit Discogs via `lookup.py`.
- Nooit een veld invullen dat je niet echt gelezen hebt.
