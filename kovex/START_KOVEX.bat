@echo off
REM ===========================================================================
REM Kovex - Demarrage Windows
REM Double-cliquez sur ce fichier pour lancer Kovex.
REM
REM Remplace START_PYGIA.bat. Trois differences qui comptent :
REM  - l'interface est servie par serve_frontend.py, qui interdit la mise en
REM    cache : sans cela le navigateur resservait un index.html perime apres
REM    chaque livraison, et un defaut corrige paraissait toujours present ;
REM  - les dependances sont verifiees une par une, avec un message qui nomme
REM    celle qui manque ;
REM  - les ports sont lus dans l'environnement, plus ecrits en dur.
REM ===========================================================================

setlocal enabledelayedexpansion
title Kovex - Demarrage

REM Se placer dans le dossier du produit.
REM
REM Les chemins des fichiers sources sont relatifs dans config.json : ils sont
REM resolus contre le repertoire de travail. Un double-clic le place ici, mais
REM un raccourci avec un "Demarrer dans" different, une tache planifiee ou un
REM service demarre ailleurs -- et Kovex se lance alors sans erreur visible en
REM ne trouvant aucune donnee. On ne laisse pas ce choix au hasard.
cd /d "%~dp0"


if "%KOVEX_API_PORT%"=="" set KOVEX_API_PORT=8000
if "%KOVEX_FRONTEND_PORT%"=="" set KOVEX_FRONTEND_PORT=3000

echo.
echo ========================================
echo     Kovex - Gouvernance des identites
echo ========================================
echo.

REM --- Python -------------------------------------------------------------
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Python n'est pas installe ou pas dans le PATH.
    echo Installez Python depuis https://www.python.org/
    pause
    exit /b 1
)
echo [OK] Python trouve

REM --- Nettoyage des caches Python ---------------------------------------
REM Un .pyc laisse par une version precedente peut masquer une correction.
echo [INFO] Nettoyage des caches Python...
for /r src %%i in (*.pyc) do @del /q "%%i" 2>nul
for /d /r src %%d in (__pycache__) do @if exist "%%d" rmdir /s /q "%%d" 2>nul
del /q *.pyc 2>nul
echo [OK] Caches nettoyes

REM --- Dependances --------------------------------------------------------
REM Chacune est verifiee separement : "il manque reportlab" est exploitable,
REM "l'installation a echoue" ne l'est pas.
set MANQUE=
for %%p in (fastapi uvicorn pandas scipy openpyxl reportlab jwt) do (
    python -c "import %%p" >nul 2>&1
    if errorlevel 1 set MANQUE=!MANQUE! %%p
)
if not "!MANQUE!"=="" (
    echo [INFO] Dependances manquantes :!MANQUE!
    echo [INFO] Installation depuis requirements.txt...
    REM Sur un serveur isole cette commande echoue faute de reseau : les
    REM dependances doivent y avoir ete installees au prealable.
    pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo [ERREUR] Installation impossible. Sur un poste sans acces reseau,
        echo          installez les dependances depuis un depot interne :
        echo          pip install --no-index --find-links ^<dossier^> -r requirements.txt
        pause
        exit /b 1
    )
)
echo [OK] Dependances verifiees

REM --- Fichier .env -------------------------------------------------------
REM La cle de signature est tiree au hasard a la creation : une cle ecrite
REM dans ce script serait connue de quiconque lit le depot, et permettrait de
REM fabriquer un jeton administrateur valide sur toutes les installations.
if not exist ".env" (
    echo [INFO] Creation du fichier .env...
    python -c "import secrets; lignes=['PYGIA_ENV=development','PYGIA_SECRET_KEY='+secrets.token_hex(32),'PYGIA_AUTH_DISABLED=false','PYGIA_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,http://localhost:8000','PYGIA_LOG_LEVEL=INFO','PYGIA_RATE_LIMIT=true','PYGIA_AUDIT_FILE=']; open('.env','w',encoding='utf-8').write(chr(10).join(lignes)+chr(10))"
    echo [OK] Fichier .env cree avec une cle unique
)

echo.
echo ========================================
echo Demarrage des serveurs...
echo ========================================
echo.
echo API       : http://127.0.0.1:%KOVEX_API_PORT%
echo Interface : http://localhost:%KOVEX_FRONTEND_PORT%
echo.

start "Kovex API" cmd /c "python run_api.py"
timeout /t 3 /nobreak >nul

echo [INFO] Demarrage de l'interface...
start "Kovex Interface" cmd /c "python serve_frontend.py"
timeout /t 2 /nobreak >nul

echo [INFO] Ouverture du navigateur...
start http://localhost:%KOVEX_FRONTEND_PORT%

echo.
echo ========================================
echo Kovex est demarre.
echo.
echo Compte administrateur :
echo   Au premier demarrage, un mot de passe aleatoire est genere et
echo   affiche UNE SEULE FOIS dans la console de l'API. Notez-le.
echo   Il n'existe aucun compte par defaut.
echo.
echo Pour arreter : STOP_KOVEX.bat
echo ========================================
echo.
echo Appuyez sur une touche pour fermer cette fenetre.
echo (Les serveurs continueront de tourner.)
pause >nul
endlocal
