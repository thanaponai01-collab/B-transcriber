@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo CutDeck needs the existing project Python environment in .venv.
  pause
  exit /b 1
)
echo Keep this helper open while using the CutDeck Premiere panel.
".venv\Scripts\python.exe" -m cutdeck.xml_bridge
if errorlevel 1 pause
