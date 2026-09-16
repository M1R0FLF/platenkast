# Platenkast

Je platenverzameling fotograferen en er een kast van maken die weet wat erin
staat: welke persing precies, uit welk jaar en welk land, en wat hij waard is.
Verkopen kan daarna, maar dat is niet waar het om begint.

Het werk zit in dat woord **precies**. "Never Can Say Goodbye van Gloria
Gaynor" is geen antwoord: daar bestaan tientallen persingen van en die
verschillen een factor tien in prijs. Het antwoord is de Duitse MGM-persing uit
1975 met catalogusnummer 2315 321, en dat staat nergens anders dan in het
kleine drukwerk op de hoes zelf.

## Wat het doet

Je fotografeert elke plaat: voorkant, dan achterkant. De rest gaat vanzelf.

1. **Uitsnijden** - de hoes uit de foto halen en rechtop zetten, hoe hij ook op
   de vloer lag
2. **Lezen** - alle tekst van de hoes, op volle resolutie, want
   catalogusnummers zijn klein gedrukt
3. **Groeperen** - welke foto's horen bij dezelfde plaat
4. **Herkennen** - de juiste persing op Discogs vinden, en die keuze
   *verifiëren* voordat hij geaccepteerd wordt
5. **Waarderen** - marktprijs erbij, en een advertentietekst als je wilt
   verkopen

Op een set van 225 foto's: **100 platen, 97 herkend**. Van die 97 klopt de
persing aantoonbaar bij 90; bij de andere 7 staat er te weinig leesbare tekst
op de hoes om het te kunnen nakijken. **Nul tegenspraken.**

## Liever niets dan iets verkeerds

Een verkeerde persing levert een verkeerde prijs op, en dat merkt niemand meer.
Daarom wordt elke keuze getoetst aan bewijs dat op de hoes zelf staat - het
catalogusnummer, de tracklist, het hoesbeeld - en gaat wat daar niet doorheen
komt naar een handmatige lijst. Drie van de honderd staan daar, met de reden
erbij.

Dat is een bewuste afweging: liever drie platen zelf opzoeken dan honderd
waarvan je er een paar niet vertrouwt.

## Aan de slag

```
pip install -r v2/vereisten.txt
cd v2
py kast.py
```

Dat opent de kast in je browser. Voor prijzen is een gratis Discogs-token
nodig (discogs.com → Settings → Developers → Generate token), eenmalig te
zetten met:

```powershell
[Environment]::SetEnvironmentVariable("DISCOGS_TOKEN","jouw-token","User")
```

Het uitsnijden en lezen draait op je eigen computer - negen seconden per foto,
dus een half uur voor tweehonderd. Dat hoort daar ook: je foto's hoeven
nergens heen en je betaalt niemand per seconde rekentijd.

## In deze map

| | |
|---|---|
| [`v2/`](v2/) | de huidige versie, inclusief de site. Begin hier: [v2/LEESMIJ.md](v2/LEESMIJ.md) |
| [`platen/`](platen/) | v1, af en werkend, bewaard omdat de metingen erin staan waarop v2 gebouwd is |

De foto's zelf staan niet in deze repository: ruim een gigabyte, en git bewaart
elke versie van een JPEG opnieuw.
