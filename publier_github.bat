@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title Publication de Whiteboard Studio sur GitHub

echo.
echo  ==============================================
echo     Publication sur GitHub
echo  ==============================================
echo.
echo  Premiere fois : cree le depot sur votre compte GitHub et l'envoie.
echo  Fois suivantes : envoie simplement vos modifications.
echo.

rem --- 1. Git et GitHub CLI ------------------------------------------------
where git >nul 2>nul || (
    echo Installation de Git...
    winget install -e --id Git.Git --silent --accept-package-agreements --accept-source-agreements
    set "PATH=!PATH!;%ProgramFiles%\Git\cmd"
)
where gh >nul 2>nul || (
    echo Installation de GitHub CLI...
    winget install -e --id GitHub.cli --silent --accept-package-agreements --accept-source-agreements
    set "PATH=!PATH!;%ProgramFiles%\GitHub CLI"
)
where git >nul 2>nul || goto :manque
where gh >nul 2>nul || goto :manque

rem --- 2. Connexion au compte GitHub (une seule fois) ---------------------
gh auth status >nul 2>nul
if errorlevel 1 (
    echo Connexion a GitHub : suivez les instructions, un navigateur va s'ouvrir.
    gh auth login --web --git-protocol https
    if errorlevel 1 goto :erreur
)
gh auth setup-git >nul 2>nul

rem --- 3. Depot local ----------------------------------------------------------
if not exist ".git" (
    git init -b main >nul
    if errorlevel 1 goto :erreur
)
rem Identite de l'auteur des commits : celle du compte GitHub si aucune n'est configuree
git config user.name >nul 2>nul
if errorlevel 1 (
    for /f "delims=" %%u in ('gh api user -q .login') do (
        git config user.name "%%u"
        git config user.email "%%u@users.noreply.github.com"
    )
)

git add -A
git diff --cached --quiet
if errorlevel 1 (
    git rev-parse --verify HEAD >nul 2>nul
    if errorlevel 1 (
        set "MSG=Version initiale de Whiteboard Studio"
    ) else (
        set "MSG="
        set /p "MSG=Description de cette version [Mise a jour] : "
        if not defined MSG set "MSG=Mise a jour"
    )
    git commit -q -m "!MSG!"
    if errorlevel 1 goto :erreur
) else (
    echo Aucune modification a enregistrer.
)

rem --- 4. Envoi sur GitHub -----------------------------------------------------
git remote get-url origin >nul 2>nul
if errorlevel 1 (
    set "NOM="
    set /p "NOM=Nom du depot GitHub [whiteboard-studio] : "
    if not defined NOM set "NOM=whiteboard-studio"
    choice /c PV /n /m "Depot Public (P) ou priVe (V) ? "
    if errorlevel 2 (set "VIS=--private") else (set "VIS=--public")
    gh repo create "!NOM!" !VIS! --source=. --remote=origin --push --description "Videos main qui dessine (whiteboard animation) pour YouTube"
    if errorlevel 1 goto :erreur
) else (
    git push -u origin HEAD
    if errorlevel 1 goto :erreur
)

echo.
echo  Publication terminee. Ouverture de la page du depot...
gh repo view --web
pause
exit /b 0

:manque
echo.
echo  Git ou GitHub CLI vient d'etre installe : fermez cette fenetre
echo  et relancez publier_github.bat pour qu'ils soient pris en compte.
pause
exit /b 1

:erreur
echo.
echo  La publication a echoue (voir les messages ci-dessus).
pause
exit /b 1
