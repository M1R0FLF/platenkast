@echo off
setlocal enabledelayedexpansion
title Platenkast
cd /d "%~dp0v2"

echo.
echo   PLATENKAST
echo   ----------
echo.

rem --- Python zoeken -------------------------------------------------------
rem  De Windows-launcher "py" is er bijna altijd; "python" is de terugval.
set PY=
where py >nul 2>&1 && set PY=py
if not defined PY where python >nul 2>&1 && set PY=python
if not defined PY (
  echo   Python is niet gevonden.
  echo.
  echo   Installeer het eenmalig van python.org/downloads en zet bij het
  echo   installeren het vinkje "Add python.exe to PATH" aan.
  echo.
  pause
  exit /b 1
)

rem --- Zijn de pakketten er al? --------------------------------------------
rem  Eerst kijken of de Python die je al hebt genoeg is. Blind een venv
rem  aanmaken kost een paar honderd megabyte downloaden voor niets.
set MOTOR=%PY%
%PY% -c "import cv2, numpy, requests, rapidocr_onnxruntime" >nul 2>&1
if errorlevel 1 (
  if exist ".venv\Scripts\python.exe" (
    set MOTOR=.venv\Scripts\python.exe
  ) else (
    echo   Eenmalig installeren. Dit duurt een paar minuten en haalt
    echo   ongeveer 300 MB op. Daarna start hij meteen.
    echo.
    %PY% -m venv .venv
    if errorlevel 1 goto :mislukt
    set MOTOR=.venv\Scripts\python.exe
    .venv\Scripts\python.exe -m pip install --upgrade pip --quiet
    .venv\Scripts\python.exe -m pip install -r vereisten.txt
    if errorlevel 1 goto :mislukt
    echo.
    echo   Klaar met installeren.
    echo.
  )
)

rem --- Token melden, niet eisen --------------------------------------------
if not defined DISCOGS_TOKEN (
  echo   Let op: geen DISCOGS_TOKEN, dus geen prijzen en ruim twee keer trager.
  echo   Gratis via discogs.com ^> Settings ^> Developers ^> Generate token,
  echo   daarna eenmalig in PowerShell:
  echo.
  echo     [Environment]::SetEnvironmentVariable("DISCOGS_TOKEN","jouw-token","User")
  echo.
)

echo   De kast opent zo in je browser. Dit venster mag open blijven staan:
echo   zodra je het sluit, stopt de kast.
echo.

rem  Alles wat je achter Platenkast.bat zet gaat door naar kast.py, dus
rem  "Platenkast.bat --poort 7390" werkt als 7385 bezet is.
%MOTOR% kast.py %*
goto :einde

:mislukt
echo.
echo   Het installeren is misgegaan. De melding hierboven zegt waarom.
echo.
pause
exit /b 1

:einde
echo.
echo   De kast is gestopt.
pause
