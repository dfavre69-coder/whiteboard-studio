@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Premiere utilisation : installation en cours...
    call install.bat
    exit /b
)
start "" ".venv\Scripts\pythonw.exe" -m whiteboard %*
