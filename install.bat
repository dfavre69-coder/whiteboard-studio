@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Installation de Whiteboard Studio

echo.
echo  ==============================================
echo     Whiteboard Studio - installation
echo  ==============================================
echo.

rem ---------------------------------------------------------------
rem 1. Trouver Python 3.10 ou plus recent (sinon l'installer)
rem ---------------------------------------------------------------
set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "PY=py -3"
if not defined PY (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo [1/4] Python introuvable : installation de Python 3.12 avec winget...
    where winget >nul 2>nul
    if errorlevel 1 goto :sans_winget
    winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
    if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
        set PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    ) else (
        py -3 -c "import sys" >nul 2>nul && set "PY=py -3"
    )
)
if not defined PY goto :sans_winget
echo [1/4] Python trouve :
%PY% --version

rem ---------------------------------------------------------------
rem 2. Environnement isole (.venv) pour ne rien toucher au systeme
rem ---------------------------------------------------------------
if not exist ".venv\Scripts\python.exe" (
    echo [2/4] Creation de l'environnement .venv...
    %PY% -m venv .venv
    if errorlevel 1 goto :erreur
) else (
    echo [2/4] Environnement .venv deja present.
)

rem ---------------------------------------------------------------
rem 3. Dependances (numpy, OpenCV, Pillow, ffmpeg)
rem ---------------------------------------------------------------
echo [3/4] Installation des dependances (quelques minutes la premiere fois)...
".venv\Scripts\python.exe" -m pip install --upgrade pip --disable-pip-version-check -q
".venv\Scripts\python.exe" -m pip install -r requirements.txt --disable-pip-version-check -q
if errorlevel 1 goto :erreur
".venv\Scripts\python.exe" -c "import tkinter, cv2, PIL, numpy, svgelements, imageio_ffmpeg; imageio_ffmpeg.get_ffmpeg_exe()"
if errorlevel 1 goto :erreur

rem ---------------------------------------------------------------
rem 4. Raccourcis sur le Bureau et dans le menu Demarrer
rem ---------------------------------------------------------------
echo [4/4] Creation des raccourcis...
set "DOSSIER=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$d = $env:DOSSIER; $w = New-Object -ComObject WScript.Shell;" ^
  "foreach ($cible in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {" ^
  "  $s = $w.CreateShortcut((Join-Path $cible 'Whiteboard Studio.lnk'));" ^
  "  $s.TargetPath = (Join-Path $d '.venv\Scripts\pythonw.exe');" ^
  "  $s.Arguments = '-m whiteboard';" ^
  "  $s.WorkingDirectory = $d;" ^
  "  $s.IconLocation = (Join-Path $d 'whiteboard\assets\icone.ico');" ^
  "  $s.Description = 'Videos main qui dessine';" ^
  "  $s.Save() }"

echo.
echo  Installation terminee !
echo  Un raccourci "Whiteboard Studio" est sur le Bureau.
echo.
choice /c ON /n /m "Lancer Whiteboard Studio maintenant ? [O/N] "
if errorlevel 2 goto :fin
start "" ".venv\Scripts\pythonw.exe" -m whiteboard
goto :fin

:sans_winget
echo.
echo  Python 3.10+ est necessaire et n'a pas pu etre installe automatiquement.
echo  La page de telechargement va s'ouvrir : installez Python en cochant
echo  "Add python.exe to PATH", puis relancez install.bat.
start "" https://www.python.org/downloads/windows/
pause
exit /b 1

:erreur
echo.
echo  L'installation a echoue (voir les messages ci-dessus).
echo  Verifiez la connexion Internet puis relancez install.bat.
pause
exit /b 1

:fin
endlocal
exit /b 0
