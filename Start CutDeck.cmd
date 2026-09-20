@echo off
setlocal
cd /d "%~dp0"
set "PY="
if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
) else (
  where python >nul 2>nul
  if not errorlevel 1 (
    set "PY=python"
  )
)

if "%PY%"=="" (
  echo CutDeck needs Python installed and available in PATH or in .venv.
  pause
  exit /b 1
)

echo Keep this helper open while using the CutDeck Premiere panel.
"%PY%" -m cutdeck.xml_bridge
if errorlevel 1 pause
