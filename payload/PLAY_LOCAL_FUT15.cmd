@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title FIFA 15 Local FUT Launcher v0.2.39 Public Test 1

rem Always run elevated: Program Files routing files may need to be regenerated
rem when Windows has reserved one of FIFA's preferred localhost ports.
fltmc >nul 2>nul
if errorlevel 1 (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo ============================================================
echo  FIFA 15 LOCAL FUT v0.2.39 Public Test 1
echo ============================================================
echo  Starting local server + FIFA 15...
echo.

if not exist "%~dp0fifa15.exe" (
    echo ERROR: fifa15.exe was not found beside this launcher.
    pause
    exit /b 1
)

if not exist "%~dp0WAIT_FOR_LOCAL_FUT.ps1" (
    echo ERROR: WAIT_FOR_LOCAL_FUT.ps1 is missing from this folder.
    echo The Local FUT files are incomplete - reinstall the release package.
    pause
    exit /b 1
)

call "%~dp0STOP_LOCAL_FUT15.cmd" /quiet >nul 2>nul
del /q "%LOCALAPPDATA%\FIFA15LocalFUT\startup_phase.txt" >nul 2>nul
start "FIFA 15 Local FUT Server" cmd /c ""%~dp0START_LOCAL_FUT15.cmd""

rem Readiness is waited on by WAIT_FOR_LOCAL_FUT.ps1: one process, a real
rem deadline, and a specific exit code describing what went wrong. Override the
rem deadline with "set LOCALFUT_WAIT_SECONDS=300" before running this launcher.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0WAIT_FOR_LOCAL_FUT.ps1"
set "RC=%ERRORLEVEL%"
if "%RC%"=="0" goto :launch

echo.
echo ERROR: Local FUT did not become ready, so FIFA will NOT be launched.
echo.
if "%RC%"=="2" (
    echo The server stopped on its own. The Local FUT Server window shows the
    echo exact failing service and port - read it before closing it.
)
if "%RC%"=="3" (
    echo The server and this launcher are running under different Windows
    echo accounts, so they do not share the same LocalAppData folder.
    echo Run PLAY_LOCAL_FUT15.cmd with "Run as administrator" from an account
    echo that is itself an administrator, instead of entering another
    echo account's credentials at the UAC prompt.
)
if "%RC%"=="4" (
    echo The server is up but nothing can reach it on localhost. A security
    echo suite or firewall is most likely intercepting loopback connections.
    echo Run PORT_DIAGNOSTICS.cmd and LOCAL_FUT_STATUS.cmd for details.
)
if "%RC%"=="5" (
    echo The server is still installing the Python "cryptography" package.
    echo Run INSTALL_PREREQUISITES.cmd once, let it finish, then run this
    echo launcher again - the second start is much faster.
)
if "%RC%"=="1" (
    echo Check the Local FUT Server window for the exact failing port.
    echo You can also run PORT_DIAGNOSTICS.cmd.
)
echo.
echo If the server window reaches READY shortly after this message, the wait
echo deadline was simply too short: set LOCALFUT_WAIT_SECONDS=300 and retry.
echo.
pause
exit /b 2

:launch
echo Local FUT is ready. Launching FIFA 15...
start "" "%~dp0fifa15.exe"
exit /b 0
