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


call "%~dp0STOP_LOCAL_FUT15.cmd" /quiet >nul 2>nul
start "FIFA 15 Local FUT Server" cmd /c ""%~dp0START_LOCAL_FUT15.cmd""

echo Waiting for localhost FUT service...
set "READY=0"
for /L %%I in (1,1,30) do (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$f=Join-Path $env:LOCALAPPDATA 'FIFA15LocalFUT\runtime_ports.json'; if(-not (Test-Path $f)){exit 1}; try{$p=[int]((Get-Content $f -Raw | ConvertFrom-Json).fut_port); $c=New-Object Net.Sockets.TcpClient; $a=$c.BeginConnect('127.0.0.1',$p,$null,$null); if(-not $a.AsyncWaitHandle.WaitOne(300)){ $c.Close(); exit 1 }; $c.EndConnect($a); $c.Close(); exit 0}catch{exit 1}" >nul 2>nul
    if not errorlevel 1 (
        set "READY=1"
        goto :launch
    )
    timeout /t 1 /nobreak >nul
)

:launch
if "%READY%"=="0" (
    echo.
    echo ERROR: Local FUT did not become ready, so FIFA will NOT be launched.
    echo Check the Local FUT Server window for the exact failing port.
    echo You can also run PORT_DIAGNOSTICS.cmd.
    echo.
    pause
    exit /b 2
)

echo Local FUT is ready. Launching FIFA 15...
start "" "%~dp0fifa15.exe"
exit /b 0
