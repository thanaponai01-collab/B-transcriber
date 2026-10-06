@echo off
setlocal
cd /d "%~dp0"
set "CLUBFRIDAY_PY=python"
if exist ".venv\Scripts\python.exe" set "CLUBFRIDAY_PY=.venv\Scripts\python.exe"
"%CLUBFRIDAY_PY%" -m clubfriday.server
if errorlevel 1 pause
