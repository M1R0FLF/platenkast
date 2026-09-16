# setup.ps1 - eenmalig. Maakt de mappen, controleert wat er nodig is en
# onthoudt waar tesseract staat.
#
#   powershell -ExecutionPolicy Bypass -File .\setup.ps1

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

Write-Host "`n=== Mappen ===" -ForegroundColor Cyan
foreach ($m in @("fotos", "bijgeknipt", "kit", "handmatig", "uitvoer", "reserve")) {
    $p = Join-Path $root $m
    if (Test-Path $p) { Write-Host "  bestaat  $m" }
    else { New-Item -ItemType Directory -Path $p | Out-Null; Write-Host "  gemaakt  $m" -ForegroundColor Green }
}

Write-Host "`n=== Python ===" -ForegroundColor Cyan
try {
    $pv = & py --version 2>&1
    Write-Host "  $pv"
} catch {
    Write-Host "  py niet gevonden. Installeer Python via python.org en vink" -ForegroundColor Red
    Write-Host "  'Add python.exe to PATH' aan. Sluit daarna dit venster en open een nieuw." -ForegroundColor Red
    exit 1
}

Write-Host "`n=== Pakketten ===" -ForegroundColor Cyan
& py -m pip install --quiet --disable-pip-version-check opencv-python numpy requests
foreach ($m in @("cv2", "numpy", "requests")) {
    $ok = & py -c "import $m; print('ok')" 2>&1
    if ($ok -match "ok") { Write-Host "  ok       $m" } else { Write-Host "  ONTBREEKT $m" -ForegroundColor Red }
}

Write-Host "`n=== Tesseract ===" -ForegroundColor Cyan
$kandidaten = @(
    "C:\Program Files\Tesseract-OCR\tesseract.exe",
    "C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    "$env:LOCALAPPDATA\Programs\Tesseract-OCR\tesseract.exe"
)
$tess = $kandidaten | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $tess) {
    $inPath = Get-Command tesseract -ErrorAction SilentlyContinue
    if ($inPath) { $tess = $inPath.Source }
}
if ($tess) {
    $v = (& $tess --version 2>&1 | Select-Object -First 1)
    Write-Host "  $v"
    Write-Host "  pad: $tess"
    $langs = & $tess --list-langs 2>&1
    if ($langs -match "osd") { Write-Host "  osd aanwezig" }
    else { Write-Host "  osd ontbreekt: rechtzetten werkt minder goed" -ForegroundColor Yellow }
    Set-Content -Path (Join-Path $root "tesseract_pad.txt") -Value $tess -Encoding UTF8
} else {
    Write-Host "  niet gevonden. Haal de 64-bit installer op github.com/UB-Mannheim/tesseract/wiki" -ForegroundColor Red
    Write-Host "  en draai dit script daarna opnieuw." -ForegroundColor Red
}

Write-Host "`n=== Discogs ===" -ForegroundColor Cyan
if ($env:DISCOGS_TOKEN) {
    Write-Host "  token staat in dit venster"
} else {
    Write-Host "  geen token. Gratis via discogs.com > Settings > Developers > Generate token." -ForegroundColor Yellow
    Write-Host "  Zet hem permanent met:" -ForegroundColor Yellow
    Write-Host '    [Environment]::SetEnvironmentVariable("DISCOGS_TOKEN","jouw-token","User")' -ForegroundColor Yellow
    Write-Host "  Daarna een nieuw venster openen." -ForegroundColor Yellow
}

$n = (Get-ChildItem (Join-Path $root "fotos") -Filter *.jpg -ErrorAction SilentlyContinue).Count
Write-Host "`n=== Klaar ===" -ForegroundColor Cyan
Write-Host "  $n foto's in fotos\"
if ($n -eq 0) { Write-Host "  Kopieer je foto's naar de map fotos\ en draai dan: .\run.ps1" }
else { Write-Host "  Volgende stap: .\run.ps1" }
Write-Host ""
