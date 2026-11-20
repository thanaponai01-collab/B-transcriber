@echo off
setlocal
cd /d "%~dp0"
set "SUBTITLEDESK_PY=python"
if exist ".venv\Scripts\python.exe" set "SUBTITLEDESK_PY=.venv\Scripts\python.exe"
"%SUBTITLEDESK_PY%" -m subtitle_desk.server
if errorlevel 1 pause
