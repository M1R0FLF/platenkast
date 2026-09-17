# Platenkast v2

Je platen fotograferen, ze laten herkennen, en weten wat je hebt - welke
persing, uit welk jaar, wat hij waard is. Wat je daarna verkoopt is aan jou.

```
py kast.py                     de kast openen in je browser (dit is de gewone ingang)

py run.py                      alleen de keten: uitsnijden, lezen, groeperen, opzoeken
py prijs.py uit/platen.json uit/platen.csv
py hergroep.py                 grenzen en persingen uit het BEELD (zie hieronder)
py hersnij.py                  opnieuw snijden met de hoes op Discogs als mal
py stand.py                    de uitsnedes rechtop
py exporteer.py                keten -> site: collectie.json en duimnagels
py verkooplijst.py             de korte lijst om mee te verkopen
py contactvel.py               een tegel per plaat, met artiest en prijs
py contactvel.py --alles       elke uitsnede, om het snijden te keuren
py nauwkeurig.py               klopt de gekozen persing met wat op de hoes staat?
```

Eenmalig: `pip install -r vereisten.txt`, en een gratis Discogs-token in
`DISCOGS_TOKEN` als je prijzen wilt.

## Twee rondes, en waarom

De keten draait twee keer, en dat is geen omweg maar de kern.

In de eerste ronde weet niemand nog welke plaat het is. `knip` moet de rand van
de hoes ZOEKEN, `knip.rechtop` moet de draaiing RADEN en `groep` moet de grens
tussen twee platen uit de tekst afleiden. Op een hoes vol drukwerk gaat dat
goed. Op een fotohoes met drie woorden erop niet, en gemeten was dat geen
uitzondering: 16 van de 90 voorkanten verkeerd gesneden, 22 procent verkeerd
gedraaid, en hele reeksen in paren geknipt op plekken waar geen plaat begon.

Na de eerste ronde staat de persing vast, en daarmee staat de hoes op Discogs.
Dan hoeft er niets meer geraden te worden:

| | wat het meet | waar het heen schrijft |
|---|---|---|
| `hergroep.py` | welke foto bij welke persing hoort | `uit/fotolabels.json`, `hints.json` |
| `hersnij.py` | waar de rand van de hoes echt ligt | `uit/snijquads.json` |
| `stand.py` | hoe de hoes gedraaid staat | de uitsnedes zelf |

Die drie bestanden leest de tweede ronde terug. `run.py` neemt de grenzen over,
`foto.py` gebruikt de opgemeten vierhoek in plaats van er een te zoeken, en
`match.herken` slaat het zoeken over als de persing al bekend is. Gemeten
scheelde dat laatste 18m07s en 647 Discogs-aanroepen tegen 3m22s en nul.

ORB is rotatie-invariant, dus een scheve of half afgesneden uitsnede matcht nog
steeds met de hoes op Discogs - en de homografie die eruit komt BEVAT de
draaiing en de vier hoeken. Dat is geen schatting maar een meting.

## De site

`site/` is een gewone statische site: geen bouwstap, geen npm, geen framework.
Dezelfde bestanden draaien op twee plekken, en dat is met opzet:

| | |
|---|---|
| `py kast.py` | serveert `site/` op 127.0.0.1 **plus** `/api/*`, dus daar werkt het tabblad Verwerken |
| Vercel | serveert alleen `site/`; zonder `/api` verandert Verwerken vanzelf in de uitleg hoe je het lokaal draait |

Het rekenwerk hoort lokaal en nergens anders. Een hoes uitsnijden en lezen kost
negen seconden; tweehonderd foto's is een half uur rekenwerk, tegen een
plafond van 800 seconden per aanroep bij Vercel en een rekening per GB-uur. En
je foto's hoeven er niet heen.

Je kast staat in IndexedDB in je eigen browser, in **twee gescheiden lagen**:

- `collectie` - wat de keten uitrekende. Wordt vervangen bij elke nieuwe run.
- `eigen` - jouw staat, prijs, notitie, verkocht-of-niet. Overleeft elke run.

Die scheiding is de reden dat `opslag.js` bestaat. Zaten ze in één record, dan
wist een tweede import stilletjes de conditie die je zelf had ingevuld, en dat
merk je pas als het weg is.

De foto's die klaar zijn om te uploaden staan in `hoezen/` - 225 stuks,
uitgesneden, rechtgezet en op naam van de oorspronkelijke foto. Welke foto's bij
welke plaat horen staat in de kolom `foto's` van de verkooplijst, voorkant
eerst.

## Wat er anders is dan in v1

**Rekenwerk en netwerk lopen naast elkaar.** De twee knelpunten gebruiken
verschillende dingen:

| | schaalt met | tijd voor 225 foto's |
|---|---|---|
| uitsnijden + OCR | je kernen | ~8 min op 12 kernen |
| Discogs opzoeken | niets, 60 aanroepen/min is het plafond | ~15 min koud |

In v1 waren dat losse stappen achter elkaar, dus de totale tijd was de som.
Hier gaat een plaat naar Discogs zodra hij compleet is, terwijl de volgende
foto's nog gelezen worden, en is de totale tijd de grootste van de twee.

Dat kan omdat Miro **altijd** voorkant, achterkant, dan binnenwerk
fotografeert: een plaat is af zodra de volgende voorkant begint, dus er is maar
een klein stukje vooruitkijken nodig. De groepering draait daarom over een
schuivend venster van 16 foto's in plaats van over de hele set, en levert
**exact dezelfde 100 platen** op als de globale berekening van v1.

**Een doorloop per foto in plaats van drie.** Gemeten per foto: uitsnijden
1,0s, maar OCR 8s - en dat is bijna onafhankelijk van de resolutie (6,8s op
1200 pixels, 10,4s op 3200). De kosten zitten in het model, niet in de pixels.
v1 las daardoor drie keer: eerst om de stand te bepalen, dan de hoes, dan
achteraf nog eens op volle resolutie (`herlees.py`). Nu een keer.

**Uitsnijden op volle resolutie.** v1 schaalde terug naar 1600 pixels en daar
ging klein drukwerk aan kapot: "R. / BANK / DANR" werd op de originele foto
"Gilbert O'Sullivan / HIMSELF / MAM-SS501".

**Kandidaten met een meetlat, geen terugval** (`knip.py`). De oude aanpak had
lijndetectie met een kleurmasker als terugval. Dat werkte niet, want de fout
was zelden "niets gevonden" - de fout was "met overtuiging het verkeerde
gevonden", en daar springt een terugval nooit voor aan. Nu leveren vijf
methodes elk een kandidaat en kiest een losse meetlat: *ligt er vloer vlak
buiten deze rand, en geen vloer vlak binnen*. Diezelfde meetlat schuift daarna
elke rand apart naar de echte overgang.

Gemeten over 225 foto's: geen enkele mislukking meer (was 4). Op het contactvel
is nog een handvol uitsnedes aan te wijzen waar vloer blijft staan; dat is
geteld met het oog, niet gemeten. De grootste winst kwam van het
schrappen van een regel die zichzelf had ingegraven: "een gatefold ligt breder
dan hoog". Dat geldt voor het eindresultaat, niet voor de foto - een
opengeklapte hoes ligt net zo vaak op zijn kant op de vloer. Drie van de vijf
slechtste uitsnedes waren al perfect gevonden en werden op die regel weggegooid.

**Rechtzetten met twee goedkope vragen** in plaats van vier dure. v1 las de hoes
in alle vier de standen en telde de woorden; bij weinig tekst kwam dat antwoord
uit ruis. Nu: de VORM van de tekstvakken zegt of de hoes een kwartslag moet
("LADY IN BLUE" is liggend een brede streep) en dat komt uit de detectiestap,
zonder een letter te lezen; het hoekmodel van RapidOCR zegt of hij ondersteboven
staat. Daardoor worden omgekeerde hoezen nu überhaupt gevonden - v1 vond er nul.

Een hoes zonder enige tekst is niet te bepalen. Die blijft liggen zoals hij lag
en krijgt `rechtop: false` mee, want dat is een onbekende en geen antwoord.

**SQLite in plaats van een JSON-cache** die bij elke twintig aanroepen volledig
opnieuw weggeschreven werd. Dat bestand groeide naar 38 MB.

**Draden vastgezet, anders helpen meer processen niet.** Lang stond hier dat
meer werkers trager was, met metingen erbij. Die metingen klopten, de verklaring
niet. onnxruntime pakt per sessie standaard alle kernen, en RapidOCR opent er
drie: 46 draden per proces. Zes werkers waren 276 draden op 20 kernen, en die
draadpoel wacht al draaiend, dus de kernen stonden vol met draden die op elkaar
wachtten - alle 20 bezet, en 6 foto's in 18 minuten.

De regel die dat had moeten voorkomen, `RapidOCR(intra_op_num_threads=1)`, deed
niets: RapidOCR verdeelt kwargs op hun voorvoegsel (det_, cls_, rec_) en de rest
gaat naar `Global`, waar het nooit gelezen wordt. En `OrtInferSession` maakt zijn
eigen SessionOptions zonder het aantal draden te zetten, dus er is geen sleutel
die het wél zou bereiken. Het moest via `knip._een_draad_per_sessie`. Daarna 4
draden per proces, en:

    1 werker  7,55s per foto      4 werkers 2,93s
    8 werkers 2,48s              16 werkers 2,03s

## Bestanden

| | |
|---|---|
| `run.py` | de keten: leespool + zoekdraden |
| `knip.py` | hoes uit de foto snijden en rechtop zetten |
| `foto.py` | een foto van begin tot eind: knippen, lezen, bewaren |
| `groep.py` | welke foto's horen bij dezelfde plaat |
| `velden.py` | catalogusnummer, land, jaar en zoektermen uit tekst |
| `match.py` | de persing vinden en verifieren |
| `beeld.py` | hoesfoto vergelijken met Discogs |
| `discogs.py` | API, snelheidsrem en cache |
| `prijs.py` | marktprijs en advertentietekst, schrijft de volledige CSV |
| `verkooplijst.py` | daaruit de korte lijst: elf kolommen, op artiest |
| `hergroep.py` | beeldbewijs -> harde grenzen voor het groeperen, en release-hints |
| `hersnij.py` | opnieuw snijden met de hoes op Discogs als mal |
| `stand.py` | de uitsnedes rechtop, met een tweede toets zonder Discogs |
| `nauwkeurig.py` | meet of de gekozen persing aantoonbaar klopt |
| `beeldtoets.py` | klopt de hoes bij de gekozen persing? |
| `contactvel.py` | alle uitsnedes op een vel om ze te keuren |
| `exporteer.py` | keten -> site: collectie.json en duimnagels van 600 px |
| `kast.py` | lokale server: de site plus de keten eronder |
| `site/` | de site zelf, zonder bouwstap |

`run.keten()` en `prijs.prijzen()` melden hun voortgang via een callback in
plaats van te printen. Zo draait `kast.py` precies dezelfde keten als de
opdrachtregel en maakt er een voortgangsbalk van, zonder dat er een tweede
kopie bestaat die stilletjes gaat afwijken.

`cache/` (SQLite + hoesafbeeldingen), `hoezen/` (uitgesneden, rechtop, klaar om
te uploaden), `uit/` (platen.json, handmatig.json, platen.csv).

`knip.VERSIE` staat als stempel in `hoezen/.snijversie` en in de OCR-sleutel.
Verandert het snijden, dan hoog je dat nummer op en worden de oude uitsnedes
vanzelf opnieuw gemaakt in plaats van stilletjes hergebruikt.

## Hoe een plaat herkend wordt

Drie strategieen, van goedkoop naar duur, en **de hoes heeft altijd het laatste
woord**. Komt er niets doorheen, dan gaat de plaat naar `uit/handmatig.json`.

### De hoes als veto

Het beeld was eerst alleen strategie 3: het kwam pas aan de beurt als tekst
niets opleverde. Een plaat die op tekst door de verificatie kwam werd dus nooit
met zijn eigen hoesfoto vergeleken - en precies daar zat een gat.

Op de achterkant van de ABBA-single "Under Attack" staat een advertentie voor
de rest van het fonds, met deze regel erin:

> Extrait du double album 30 cm «The Singles» - 406506

Titel en catalogusnummer van een ANDERE plaat, netjes bij elkaar, en dus exact
waar strategie 2 (titel + catalogusnummer) op afgaat. Resultaat: een dubbel-LP
uit 1982, terwijl er een 7"-single in de hoes zit. Prijs 11,50 in plaats van 3.

Dat was niet de enige. `beeldtoets.py` hield de maatlat langs alle 97 herkende
platen en vond er **vijf** waarvan de hoes niet bij de persing paste - twee
promo-persingen, twee singles die als LP waren aangezien, en deze.

De scheiding is absoluut:

    92 juiste persingen   35 tot 766 samenvallende punten
     5 foute persingen     4 tot 8
     daartussen            niets

Daarom toetst `match.herken` nu elke tekstmatch aan het beeld. Spreekt de hoes
het tegen (onder de tien punten), dan gaat de beeldronde alsnog zoeken - en die
vond vier van de vijf alsnog goed. De vijfde ging eerlijk naar de handmatige
lijst.

Kosten: **0,39 seconde per plaat**, 37 seconden over de hele set, op een run
van anderhalve minuut. Te goedkoop om over na te denken.

Let op: dit is de enige toets die NIET uit de OCR komt. `nauwkeurig.py` toetst
het catalogusnummer en de titel tegen de OCR, en kan een achterkant vol reclame
per definitie niet betrappen - die leest immers dezelfde tekst. Beide getallen
zijn nodig; ze meten niet hetzelfde.

1. **tracklist** - genoeg tracktitels van de persing komen terug in de OCR
2. **bevestiging** - titel EN label/catalogusnummer komen terug. Nodig omdat
   lang niet elke achterkant een tracklist heeft: op "A-tom-ic Jones" staat een
   verhaal over Tom Jones en geen enkel nummer.
3. **hoesbeeld** - de foto valt meetkundig samen met de afbeelding op Discogs.
   Gemeten: juiste hoes 76 tot 766 samenvallende punten, verkeerde hoogstens 6.

Een 7"-single heeft twee nummers, dus de eis "minstens drie tracktitels" kon
die per definitie nooit halen. Voor een korte tracklist is de eis daarom niet
lager maar hoger: alles moet kloppen, of anders het catalogusnummer als anker.

## Waar we gebleven zijn

100 platen uit 225 foto's, waarvan er **97 herkend** zijn. Van die 97 klopt de
persing aantoonbaar bij 90; de andere 7 hebben te weinig OCR om het te kunnen
toetsen. **Nul tegenspraken.** CSV: 97 rijen, 83 met vraagprijs, samen 479 euro.

De drie die overblijven staan in `uit/handmatig.json` met de reden erbij. Het
zijn alle drie hetzelfde soort geval: een achterkant zonder tracklist. Bij
"A-tom-ic Jones" staat een verhaal over Tom Jones, bij de Bach-plaat de bezetting
van het orkest, en bij Streisands Greatest Hits een advertentie voor zes andere
albums - compleet met hun catalogusnummers, die alle drie keer beter aansluiten
op de zoekopdracht dan de plaat die je in handen hebt.

Wat er is geprobeerd en waarom het niet genoeg was, staat in de opmerkingen bij
`_zelfde_plaat_ander_land`, `fondslijst` in match.py en `tracktermen` in
velden.py. Streisand is het leerzaamste geval: met een ruimer patroon voor
catalogusnummers werd hij wel herkend, maar als "Je M'appelle Barbra" - een
advertentie op de achterkant. Fout is erger dan niets, dus die staat nu weer op
de handmatige lijst.

Open punten:

- 31 hoezen kregen `rechtop: false`: geen tekst, dus kop en staart zijn niet te
  bepalen. Meestal binnenwerk. Miro fotografeert het binnenwerk voortaan niet
  meer, dus dit lost zichzelf grotendeels op.
- Er staat nog geen git op deze pc (`winget install --id Git.Git -e`), dus het
  project staat nergens anders.

## Niet doen

- Geen advertenties plaatsen op 2dehands. Die stap doet Miro zelf.
- Niets wijzigen in `fotos/`.
- Prijzen niet zelf schatten, die komen uit Discogs.
- Nooit een veld invullen dat niet echt gelezen is. Liever `null`: een
  verkeerde persing levert een verkeerde prijs en dat merkt niemand nog.
