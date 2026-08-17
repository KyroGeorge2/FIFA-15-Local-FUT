@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title FIFA 15 Local FUT - Add Coins

echo ============================================================
echo  FIFA 15 LOCAL FUT - OPTIONAL COIN TOOL
echo ============================================================
echo  This changes only your LOCAL offline FUT balance.
echo.

where py.exe >nul 2>nul
if not errorlevel 1 (
    set "PY=py -3"
) else (
    where python.exe >nul 2>nul
    if errorlevel 1 (
        echo ERROR: Python 3 was not found.
        echo Run INSTALL_PREREQUISITES.cmd from the release package first.
        pause
        exit /b 1
    )
    set "PY=python"
)

set "AMOUNT="
set /p "AMOUNT=Coins to add [default 1000000]: "
if not defined AMOUNT set "AMOUNT=1000000"
%PY% "%~dp0localfut15\add_coins.py" "%AMOUNT%"
echo.
pause
endlocal
