@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title FIFA 15 Local FUT Public Test

fltmc >nul 2>nul
if errorlevel 1 (
    echo Requesting administrator permission for the FIFA 15 install folder...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo ============================================================
echo  FIFA 15 LOCAL FUT v0.2.39 - PUBLIC TEST 1
echo ============================================================
echo.

rem Prerequisite sanity check. The dedicated prerequisite script handles installs.
set "PY="
where py.exe >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if not defined PY (
  where python.exe >nul 2>nul
  if not errorlevel 1 set "PY=python"
)
if not defined PY goto :prereq_missing
%PY% -c "import sys,cryptography; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
if errorlevel 1 goto :prereq_missing
if not exist "%WINDIR%\System32\msvcr110.dll" goto :prereq_missing

set "SRC=%~dp0payload"
if not exist "%SRC%\localfut15\server.py" (
    echo ERROR: The payload folder is missing or incomplete.
    pause
    exit /b 2
)

set "GAME="
for /f "usebackq delims=" %%G in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$c=@(); $reg=@('HKLM:\SOFTWARE\EA Games\FIFA 15','HKLM:\SOFTWARE\WOW6432Node\EA Games\FIFA 15','HKCU:\SOFTWARE\EA Games\FIFA 15'); foreach($r in $reg){try{$p=Get-ItemProperty $r -ErrorAction Stop; foreach($n in 'Install Dir','InstallDir','InstallLocation'){if($p.PSObject.Properties.Name -contains $n){$v=$p.$n; if($v){$c+=$v}}}}catch{}}; $c += @('C:\Program Files\EA Games\FIFA 15\Game','C:\Program Files\EA Games\FIFA 15','C:\Program Files (x86)\Origin Games\FIFA 15','C:\Program Files\Origin Games\FIFA 15','C:\Program Files (x86)\EA Games\FIFA 15\Game','C:\Program Files (x86)\EA Games\FIFA 15'); foreach($x in $c){if(Test-Path (Join-Path $x 'fifa15.exe')){Write-Output $x; break}; if(Test-Path (Join-Path $x 'Game\fifa15.exe')){Write-Output (Join-Path $x 'Game'); break}}"`) do if not defined GAME set "GAME=%%G"
if not defined GAME (
    echo FIFA 15 was not found automatically.
    set /p "GAME=Folder containing fifa15.exe: "
)
if defined GAME if "!GAME:~-1!"=="\" set "GAME=!GAME:~0,-1!"
if not exist "%GAME%\fifa15.exe" (
    echo ERROR: fifa15.exe was not found in "%GAME%".
    pause
    exit /b 3
)

set "BACKUP=%LOCALAPPDATA%\FIFA15LocalFUT\install-backup"
if not exist "%BACKUP%" mkdir "%BACKUP%" >nul 2>nul

rem Stop an old Local FUT instance before copying a newer public-test payload.
if exist "%GAME%\STOP_LOCAL_FUT15.cmd" call "%GAME%\STOP_LOCAL_FUT15.cmd" /quiet >nul 2>nul
taskkill /IM fifa15.exe /F >nul 2>nul

for %%F in (dinput8.dll CardsDLLzf.dll ItsAMe_Origin.dll EA-MITM.ini cl.ini data_patch.big data_patch.bh cards0.big cards0.bh) do (
    if exist "%GAME%\%%F" if not exist "%BACKUP%\%%F" copy /y "%GAME%\%%F" "%BACKUP%\%%F" >nul
)

echo Installing/updating Local FUT files...
xcopy "%SRC%\*" "%GAME%\" /E /I /H /Y >nul
if errorlevel 1 (
    echo ERROR: Could not copy Local FUT files to FIFA 15.
    pause
    exit /b 4
)

set "CARDS_DLC=%GAME%\dlc\dlc_CardsDLL\dlc\CardsDLLzf.dll"
if exist "%CARDS_DLC%" (
    if not exist "%BACKUP%\dlc_CardsDLL" mkdir "%BACKUP%\dlc_CardsDLL" >nul 2>nul
    if not exist "%BACKUP%\dlc_CardsDLL\CardsDLLzf.dll" copy /y "%CARDS_DLC%" "%BACKUP%\dlc_CardsDLL\CardsDLLzf.dll" >nul
    copy /y "%SRC%\CardsDLLzf.dll" "%CARDS_DLC%" >nul
)

if not exist "%LOCALAPPDATA%\FIFA15LocalFUT" mkdir "%LOCALAPPDATA%\FIFA15LocalFUT" >nul 2>nul
echo v0.2.39-public-test1>"%LOCALAPPDATA%\FIFA15LocalFUT\installed-version.txt"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$game='%GAME%'; $desktop=[Environment]::GetFolderPath('Desktop'); $lnk=Join-Path $desktop 'FIFA 15 Local FUT.lnk'; $w=New-Object -ComObject WScript.Shell; $s=$w.CreateShortcut($lnk); $s.TargetPath=Join-Path $game 'PLAY_LOCAL_FUT15.cmd'; $s.WorkingDirectory=$game; $s.IconLocation=(Join-Path $game 'fifa15.exe')+',0'; $s.Description='FIFA 15 Local FUT Public Test'; $s.Save()" >nul 2>nul

echo Install/update complete: %GAME%
echo Starting Local FUT...
start "" "%GAME%\PLAY_LOCAL_FUT15.cmd"
exit /b 0

:prereq_missing
echo Prerequisites are missing or incomplete.
echo Run INSTALL_PREREQUISITES.cmd first, then run this launcher again.
echo.
pause
exit /b 1
