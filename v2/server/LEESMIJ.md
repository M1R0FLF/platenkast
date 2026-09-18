# De kastserver

Dezelfde kast op je telefoon en je pc, op een machine die van jou is.

```bash
py server/kastserver.py --nodig "Miro"
```

Dat maakt een kast en drukt **één keer** een sleutel af. Bewaar hem; hij is
niet opnieuw op te vragen, want in de database staat alleen zijn afdruk.

```bash
py server/kastserver.py
```

Nu draait hij op <http://127.0.0.1:7386/>. Dat is de hele site — dezelfde
bestanden als op Vercel — met de synchronisatie eronder. Open hem, ga in het
menu (`⋯`) naar **Synchroniseren met je eigen server**, laat het adres leeg en
plak je sleutel.

Een tweede apparaat op **dezelfde** kast krijgt zijn eigen sleutel:

```bash
py server/kastserver.py --erbij <kast-id>
```

`py server/kastserver.py --wie` laat zien welke kasten er zijn en hoeveel
platen erin staan.

## Op je telefoon, thuis

```bash
py server/kastserver.py --adres 0.0.0.0
```

Nu kun je er vanaf je telefoon bij, op `http://<het-ip-van-je-pc>:7386/`.
Alleen binnen je eigen netwerk, zonder TLS. Prima om te proberen, niet om open
te zetten.

## Van buiten bereikbaar

Gebruik een tunnel (Cloudflare Tunnel, Tailscale Funnel). Dan hoef je geen
poort open te zetten, heb je geen vast IP nodig en krijg je TLS erbij:

```bash
py server/kastserver.py --veilig
cloudflared tunnel --url http://127.0.0.1:7386
```

`--veilig` zegt: er zit TLS voor, dus het sessiekoekje mag `Secure` zijn.

> **Let op de twee koppen.** De server stuurt `cross-origin-opener-policy` en
> `cross-origin-embedder-policy` mee. Knipt een tunnel of proxy die weg, dan
> laadt de site gewoon en doet alleen het **verwerken** het niet — geen
> `SharedArrayBuffer`, geen motor. Dat is een verwarrende storing, dus dat is
> het eerste om na te kijken. In de browserconsole:
> `self.crossOriginIsolated` hoort `true` te zijn.

## De site op Vercel laten staan

Kan ook: de statische site blijft waar hij is en alleen de gegevens komen van
jouw server. Dan moet die server weten wie er mag meepraten:

```bash
py server/kastserver.py --veilig --herkomst https://platenkast.vercel.app
```

Vul in het koppelscherm het adres van je server in. Dit is wél de omslachtiger
opstelling — koekjes van een ander domein, `SameSite=None`, CORS — maar het
heeft een voordeel: staat je desktop uit, dan laadt de kast nog steeds en werkt
hij door uit je browser. Hij synchroniseert alleen niet.

## Wat er in de database staat

`server/kast.db`, één SQLite-bestand. **Zet dat in je back-up.** Een oude
desktop in huis is niet vanzelf veiliger dan een telefoon; schijven gaan stuk.

```
gebruiker        de kast. Zijn id is willekeurig en betekent niets.
login            EEN manier om erop in te loggen. Nu alleen 'uitnodiging'.
sessie           aangemelde browsers.
plaat            de uitgerekende laag. Wegwerpbaar.
eigen            wat jij zelf invulde. Dit is het enige dat niet opnieuw
                 uit te rekenen is.
eigen_historie   elke overschreven versie daarvan, voor altijd.
kast             de naam van de kast.
```

Foto's staan er **niet** in. Die zijn een aparte stap: ~5 MB per foto tegenover
~1,7 KB per plaat aan gegevens.

## Waarom dit los staat van `kast.py`

`kast.py` is het gereedschap op jouw machine: hij draait de keten, opent een
mapkiezer op je bureaublad en kan `git push` doen. Geen authenticatie, en dat
hoeft ook niet — hij luistert op 127.0.0.1.

Deze server is het tegenovergestelde: hij rekent niets uit, raakt je schijf niet
aan buiten zijn eigen database, en gaat ervan uit dat wie aanklopt een vreemde
is. Twee programma's, omdat het twee vertrouwensniveaus zijn.

**Zet `kast.py` nooit open naar buiten.**

## Uitnodigingen nu, accounts later

Er is geen wachtwoord en geen registratieformulier. Een uitnodiging maak je op
de machine zelf, op de opdrachtregel — er is dus geen enkel pad van buitenaf
waarlangs iemand een account kan maken, en dus ook geen beheerderswachtwoord
dat verkeerd kan gaan.

Dat moet later kunnen veranderen, want er kan geld achter komen te zitten.
Daarom geldt in het hele schema één regel:

> **Niets hangt aan de uitnodiging. Alles hangt aan `gebruiker.id`.**

De uitnodiging is een rij in `login`. Echte accounts aanzetten is: een tweede
soort rij toevoegen (`soort='wachtwoord'`, `kenmerk=<e-mailadres>`), met een
échte sleutelafleiding in plaats van de sha256 die nu volstaat — die volstaat
omdat een uitnodiging 256 willekeurige bits zijn en een wachtwoord dat niet is.
Er verhuist dan geen enkele plaat.

`py server/proef.py` bewaakt dat: onder andere dat een tweede uitnodiging op
hetzelfde `gebruiker.id` uitkomt, dat een oudere versie een nieuwere niet
overschrijft, dat een overschreven aantekening bewaard blijft, en dat de kast
van de een onzichtbaar is voor de ander.

## Wat er gebeurt als twee apparaten elkaar tegenspreken

Per plaat wint de laatste wijziging — per **record**, niet per kast, zodat twee
apparaten die elk een andere plaat aanraken allebei winnen.

De verliezende versie van een `eigen`-record gaat niet weg maar naar
`eigen_historie`. Dat is bewust: "de nieuwste wint" geeft af en toe het
verkeerde antwoord, bijvoorbeeld bij een telefoon met een scheve klok, en er is
in deze kast nergens anders een geval waarin een aantekening van jou stilletjes
verdwijnt.

```sql
SELECT plaat, gewijzigd, vervangen, doc FROM eigen_historie ORDER BY id DESC;
```
