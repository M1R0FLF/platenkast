# run.ps1 - draait de volledige lokale keten. Alles hierin gebeurt op je eigen
# PC en kost niets. Onderbreken mag, elke stap slaat over wat al gedaan is.
#
#   .\run.ps1              alles
#   .\run.ps1 -Stap knip   alleen bijknippen
#   .\run.ps1 -Stap lees   alleen OCR (RapidOCR, ~12s per foto)
#   .\run.ps1 -Stap groep  alleen groeperen per plaat
#   .\run.ps1 -Stap auto    alleen automatisch matchen
#   .\run.ps1 -Stap herlees alleen de rest opnieuw lezen op volle resolutie
#   .\run.ps1 -Stap beeld   alleen herkennen aan de hoesafbeelding
#   .\run.ps1 -Opnieuw      negeer wat al gedaan is

param(
    [ValidateSet("alles", "knip", "lees", "groep", "auto", "herlees", "beeld")]
    [string]$Stap = "alles",
    [switch]$Opnieuw
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

$padBestand = Join-Path $root "tesseract_pad.txt"
if (-not (Test-Path $padBestand)) { Write-Host "Draai eerst .\setup.ps1" -ForegroundColor Red; exit 1 }
$tess = (Get-Content $padBestand -Raw).Trim()

function Kop($t) { Write-Host "`n=== $t ===" -ForegroundColor Cyan }
$start = Get-Date

if ($Stap -in @("alles", "knip")) {
    Kop "1/4  Bijknippen en rechtzetten"
    if ($Opnieuw -and (Test-Path .\bijgeknipt)) {
        Remove-Item .\bijgeknipt\* -Recurse -Force -ErrorAction SilentlyContinue
    }
    & py crop_sleeves.py .\fotos .\bijgeknipt --review --autorotate --tesseract $tess
    foreach ($f in @("handmatig.txt", "rechtzetten.txt")) {
        $p = ".\bijgeknipt\$f"
        if (Test-Path $p) {
            $c = (Get-Content $p | Where-Object { $_ -match '\S' }).Count
            Write-Host "  $f : $c regels" -ForegroundColor Yellow
        }
    }
}

if ($Stap -in @("alles", "lees")) {
    # Tesseract liet 27% van de foto's op nul tekens staan. RapidOCR haalt daar
    # wel tekst uit en is de reden dat het groeperen werkt. Herstartbaar.
    Kop "2/4  OCR met RapidOCR (traag, ~12s per foto, maar eenmalig)"
    if ($Opnieuw -and (Test-Path .\ocr2_cache.json)) { Remove-Item .\ocr2_cache.json -Force }
    & py leesfotos.py --indir .\bijgeknipt --cache ocr2_cache.json
}

if ($Stap -in @("alles", "groep")) {
    Kop "3/4  Groeperen per plaat en beelden klaarzetten"
    & py groepeer.py --indir .\bijgeknipt --cache ocr2_cache.json --kitdir .\kit --uit ruw2.json
}

if ($Stap -in @("alles", "auto")) {
    Kop "4/6  Automatisch matchen op Discogs"
    if (-not $env:DISCOGS_TOKEN) {
        Write-Host "  Geen DISCOGS_TOKEN, dit gaat trager." -ForegroundColor Yellow
    }
    if ($Opnieuw -and (Test-Path .\platen.json)) { Remove-Item .\platen.json -Force }
    & py automatch.py ruw2.json platen.json --rest voor_claude.json
}

if ($Stap -in @("alles", "herlees")) {
    # De bijgeknipte hoezen zijn teruggeschaald naar 1600 pixels. Voor een
    # klein catalogusnummer is dat te weinig. Wat overblijft lezen we daarom
    # nog een keer, van de originele foto's op volle resolutie.
    Kop "5/6  Rest opnieuw lezen van de originelen"
    & py herlees.py
    & py automatch.py ruw2.json platen.json --rest voor_claude.json
}

if ($Stap -in @("alles", "beeld")) {
    # Laatste redmiddel: de hoes vergelijken met de afbeelding op Discogs.
    Kop "6/6  Herkennen aan de hoes"
    $h = if (Test-Path .\hints.json) { @("--hints", "hints.json") } else { @() }
    & py beeldmatch.py @h
    & py controleer.py
}

Kop "Klaar"
Write-Host ("  duur: {0:hh\:mm\:ss}" -f ((Get-Date) - $start))
if (Test-Path .\voor_claude.json) {
    $rest = (Get-Content .\voor_claude.json -Raw | ConvertFrom-Json).Count
    if ($rest -gt 0) {
        Write-Host "  $rest platen vragen nog om Claude Code."
        Write-Host "  Start hem met:  claude"
        Write-Host "  En zeg:  Lees CLAUDE.md en werk voor_claude.json af."
    } else {
        Write-Host "  Alles is automatisch herkend. Meteen door naar:" -ForegroundColor Green
        Write-Host "    py lookup.py platen.json uitvoer\platen.csv"
    }
}
Write-Host ""
