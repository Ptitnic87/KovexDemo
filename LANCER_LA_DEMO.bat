@echo off
REM ===========================================================================
REM Kovex - Plateforme de demonstration
REM Remet les espaces de demonstration dans leur etat fige, dates du jour,
REM puis lance le Kovex du sous-module kovex\. Ce qu'une seance precedente a
REM valide ou supprime disparait ; la cle du modele, posee une fois sur ce
REM serveur, reste.
REM Les arguments sont passes a restaurer.py (ex. : --actif Alvea_ATELIER).
REM ===========================================================================
setlocal
cd /d "%~dp0"
if "%KOVEX_API_PORT%"=="" set KOVEX_API_PORT=8000

if not exist kovex\run_api.py (
    echo [ERREUR] Kovex est absent de kovex\ : git submodule update --init,
    echo          ou utilisez l'archive produite par empaqueter.py.
    pause
    exit /b 1
)

python restaurer.py --api http://127.0.0.1:%KOVEX_API_PORT% %*
if errorlevel 1 (
    echo.
    echo [ERREUR] Restauration impossible : voir le message ci-dessus.
    echo          Si Kovex tourne deja, lancez kovex\STOP_KOVEX.bat puis recommencez.
    pause
    exit /b 1
)
call kovex\START_KOVEX.bat
