@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title FIFA 15 Local FUT Server v0.2.39 Public Test 1

echo ============================================================
echo  FIFA 15 LOCAL FUT v0.2.39 Public Test 1 - RETAIL PACKS / LOCAL CLUB
echo ============================================================
echo.

where py.exe >nul 2>nul
if not errorlevel 1 (
    set "PY=py -3"
) else (
    where python.exe >nul 2>nul
    if errorlevel 1 (
        echo ERROR: Python 3 is not installed.
        echo Run INSTALL_PREREQUISITES.cmd from the release package, then try again.
        echo.
        pause
        exit /b 1
    )
    set "PY=python"
)

call "%~dp0STOP_LOCAL_FUT15.cmd" /quiet >nul 2>nul

echo Checking Python dependency...
%PY% -c "import cryptography" >nul 2>nul
if errorlevel 1 (
    echo Installing required package: cryptography
    %PY% -m pip install --user --disable-pip-version-check cryptography
    if errorlevel 1 (
        echo.
        echo ERROR: Could not install Python package 'cryptography'.
        pause
        exit /b 3
    )
)

echo Starting localhost FUT services...
echo FIFA service ports will be remapped automatically if needed.
echo If EA App/Origin already owns LSX port 3216, Local FUT will use it instead of failing.
echo.
%PY% "%~dp0localfut15\server.py"
set "RC=%ERRORLEVEL%"
echo.
echo Local FUT server exited with code %RC%.
if "%RC%"=="2" (
    echo.
    echo Startup could not recover automatically.
    echo The server log above now names the exact failing service and port.
    echo If LSX 3216 is blocked with no listener, run PORT_DIAGNOSTICS.cmd.
)
echo.
pause
exit /b %RC%
