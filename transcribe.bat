@echo off
set "PATH=%~dp0.venv\Lib\site-packages\nvidia\cublas\bin;%~dp0.venv\Lib\site-packages\nvidia\cudnn\bin;%PATH%"
"%~dp0.venv\Scripts\python.exe" "%~dp0transcribe_file.py" %*
