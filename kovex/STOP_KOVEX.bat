@echo off
REM ===========================================================================
REM Kovex - Arret des serveurs Windows
REM ===========================================================================

setlocal
title Kovex - Arret

cd /d "%~dp0"

if "%KOVEX_API_PORT%"=="" set KOVEX_API_PORT=8000
if "%KOVEX_FRONTEND_PORT%"=="" set KOVEX_FRONTEND_PORT=3000

echo.
echo ========================================
echo     Arret de Kovex
echo ========================================
echo.

for %%P in (%KOVEX_API_PORT% %KOVEX_FRONTEND_PORT%) do (
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr :%%P ^| findstr LISTENING') do (
        echo [INFO] Arret du processus sur le port %%P ^(PID %%a^)
        taskkill /PID %%a /F >nul 2>&1
    )
)

echo.
echo [OK] Kovex arrete.
echo.
pause
endlocal
