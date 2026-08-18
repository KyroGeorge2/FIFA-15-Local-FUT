@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title FIFA 15 Local FUT Server v0.2.39 Public Test 1

echo ============================================================
echo  FIFA 15 LOCAL FUT v0.2.39 Public Test 1 - RETAIL PACKS / LOCAL CLUB
echo ============================================================
echo.

rem Startup phase is published so PLAY_LOCAL_FUT15.cmd can tell "still
rem installing dependencies" apart from "server failed to bind a port".
set "RUNTIME_DIR=%LOCALAPPDATA%\FIFA15LocalFUT"
if not exist "%RUNTIME_DIR%" mkdir "%RUNTIME_DIR%" >nul 2>nul

where py.exe >nul 2>nul
if not errorlevel 1 (
    set "PY=py -3"
) else (
    where python.exe >nul 2>nul
    if errorlevel 1 (
        echo ERROR: Python 3 is not installed.
        echo Run INSTALL_PREREQUISITES.cmd from the release package, then try again.
        echo.
        del /q "%RUNTIME_DIR%\startup_phase.txt" >nul 2>nul
        pause
        exit /b 1
    )
    set "PY=python"
)

call "%~dp0STOP_LOCAL_FUT15.cmd" /quiet >nul 2>nul

echo Checking Python dependency...
>"%RUNTIME_DIR%\startup_phase.txt" echo deps
%PY% -c "import cryptography" >nul 2>nul
if errorlevel 1 (
    echo Installing required package: cryptography
    echo This is a one-time download and can take a few minutes.
    %PY% -m pip install --user --disable-pip-version-check cryptography
    if errorlevel 1 (
        echo.
        echo ERROR: Could not install Python package 'cryptography'.
        del /q "%RUNTIME_DIR%\startup_phase.txt" >nul 2>nul
        pause
        exit /b 3
    )
)

echo Starting localhost FUT services...
echo FIFA service ports will be remapped automatically if needed.
echo If EA App/Origin already owns LSX port 3216, Local FUT will use it instead of failing.
echo.
>"%RUNTIME_DIR%\startup_phase.txt" echo server
%PY% "%~dp0localfut15\server.py"
set "RC=%ERRORLEVEL%"
del /q "%RUNTIME_DIR%\startup_phase.txt" >nul 2>nul
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
