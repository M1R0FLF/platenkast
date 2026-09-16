# Platen verkopen op 2dehands

## Wat je nodig hebt

- Python, van python.org, met "Add python.exe to PATH" aangevinkt
- Tesseract, 64-bit installer van github.com/UB-Mannheim/tesseract/wiki
- Een gratis Discogs-token: discogs.com > Settings > Developers > Generate token
- Claude Code, voor de laatste moeilijke platen: `npm install -g @anthropic-ai/claude-code`

Geen Anthropic API-sleutel. Claude Code loopt op je Team-abonnement.

## Opstarten

Zet alle bestanden uit dit pakket in één map, bijvoorbeeld `C:\platen`.

```powershell
cd C:\platen
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

Dat maakt de mappen, installeert de pakketten, zoekt tesseract en onthoudt waar
die staat. Zet daarna je token permanent:

```powershell
[Environment]::SetEnvironmentVariable("DISCOGS_TOKEN","jouw-token","User")
```

Open een nieuw PowerShell-venster, anders is die nog niet actief.

## Draaien

Kopieer je foto's naar `fotos\` en dan:

```powershell
.\run.ps1
```

Dat doet drie dingen, allemaal lokaal en gratis: bijknippen en rechtzetten, OCR
en groeperen, en automatisch matchen op Discogs. Onderbreken mag, elke stap slaat
over wat al gedaan is.

Losse stappen kan ook: `.\run.ps1 -Stap knip`, `-Stap prep`, `-Stap auto`.
Alles overdoen: `.\run.ps1 -Opnieuw`.

## Tussendoor keuren

- `bijgeknipt\contactvel.jpg` — staat alles rechtop, is niets half afgesneden
- `bijgeknipt\handmatig.txt` — die knip je zelf bij en zet je in `handmatig\`
- `bijgeknipt\rechtzetten.txt` — die controleer je op draaiing

## De rest

`run.ps1` meldt op het einde hoeveel platen er overblijven. Die zitten in
`voor_claude.json`.

```powershell
claude
```

En dan: *Lees CLAUDE.md en werk voor_claude.json af.*

## Afwerken

```powershell
py lookup.py platen.json uitvoer\platen.csv
```

Open `uitvoer\platen.csv`. Per plaat staat daar de Discogs-match, het aantal
exemplaren te koop, de laagste vraagprijs, een voorgestelde vraagprijs, een
advies los-of-lot, en een kant-en-klare titel en advertentietekst.

Controleer de kolom `alternatieven` steekproefsgewijs. Bij persingen die alleen
in de matrixcode verschillen kan de match ernaast zitten, en dat zie je op geen
enkele hoesfoto.

## Publiceren

2dehands heeft geen API voor particulieren. Neem de selectors op met
`npx playwright codegen https://www.2dehands.be/plaats-zoekertje`: je plaatst één
advertentie met de hand terwijl codegen meekijkt, en je krijgt werkende Python
terug. Laat het script invullen, maar klik zelf op publiceren, en houd 30 tot 60
seconden tussen advertenties.

## Als je opnieuw begint te fotograferen

Leg de hoezen op een vel wit of zwart papier in plaats van op parket. De
uitsnijding gaat dan naar bijna honderd procent en je advertentiefoto's zijn ook
gewoon beter.
