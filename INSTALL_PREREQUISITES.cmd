@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title FIFA 15 Local FUT - Prerequisites

fltmc >nul 2>nul
if errorlevel 1 (
    echo Requesting administrator permission for runtime installation...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo ============================================================
echo  FIFA 15 LOCAL FUT - PREREQUISITES
echo ============================================================
echo  Checks/installs:
echo    - Python 3.10+
echo    - Python cryptography package
echo    - Microsoft Visual C++ 2012 runtime (x64/x86)
echo.

set "PY="
where py.exe >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if not defined PY (
    where python.exe >nul 2>nul
    if not errorlevel 1 set "PY=python"
)

if defined PY (
    %PY% -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
    if errorlevel 1 set "PY="
)

if not defined PY (
    where winget.exe >nul 2>nul
    if errorlevel 1 goto :no_winget
    echo [1/3] Installing Python 3.12...
    winget install --id Python.Python.3.12 -e --source winget --silent --accept-package-agreements --accept-source-agreements
    if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    if not defined PY (
        where py.exe >nul 2>nul
        if not errorlevel 1 set "PY=py -3"
    )
    if not defined PY (
        where python.exe >nul 2>nul
        if not errorlevel 1 set "PY=python"
    )
    if not defined PY (
        echo ERROR: Python installation finished but Python could not be located.
        echo Reboot/sign out if Windows has not refreshed PATH, then run this again.
        pause
        exit /b 2
    )
) else (
    echo [1/3] Python 3.10+ already installed.
)

echo [2/3] Installing/checking Python package: cryptography
%PY% -m pip --version >nul 2>nul
if errorlevel 1 %PY% -m ensurepip --upgrade
%PY% -m pip install --user --disable-pip-version-check --upgrade cryptography
if errorlevel 1 (
    echo ERROR: Could not install Python package cryptography.
    echo Check your internet connection and run this file again.
    pause
    exit /b 3
)

echo [3/3] Checking Microsoft Visual C++ 2012 runtime...
set "NEEDVC=0"
if not exist "%WINDIR%\System32\msvcr110.dll" set "NEEDVC=1"
if not exist "%WINDIR%\SysWOW64\msvcr110.dll" set "NEEDVC=1"
if "%NEEDVC%"=="1" (
    where winget.exe >nul 2>nul
    if errorlevel 1 goto :no_winget
    echo Installing Visual C++ 2012 x64...
    winget install --id Microsoft.VCRedist.2012.x64 -e --source winget --silent --force --accept-package-agreements --accept-source-agreements
    echo Installing Visual C++ 2012 x86...
    winget install --id Microsoft.VCRedist.2012.x86 -e --source winget --silent --force --accept-package-agreements --accept-source-agreements
) else (
    echo Visual C++ 2012 runtime already present.
)

%PY% -c "import sqlite3, cryptography; print('Python OK:', __import__('sys').version.split()[0]); print('SQLite OK:', sqlite3.sqlite_version); print('cryptography OK:', cryptography.__version__)"
if errorlevel 1 (
    echo.
    echo ERROR: Final prerequisite verification failed.
    pause
    exit /b 4
)

echo.
echo ============================================================
echo  PREREQUISITES READY
echo ============================================================
echo  Next: run PLAY_LOCAL_FUT15.cmd from this release folder.
echo.
pause
exit /b 0

:no_winget
echo.
echo ERROR: Windows Package Manager ^(winget^) is not available, so a missing
 echo prerequisite could not be installed automatically.
echo Install/update Microsoft App Installer, then run this file again.
echo.
pause
exit /b 5
