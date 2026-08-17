@echo off
setlocal EnableExtensions
fltmc >nul 2>nul
if errorlevel 1 (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
set "GAME="
for /f "usebackq delims=" %%G in (`powershell -NoProfile -Command "$c=@('C:\Program Files\EA Games\FIFA 15\Game','C:\Program Files\EA Games\FIFA 15','C:\Program Files (x86)\Origin Games\FIFA 15'); foreach($x in $c){if(Test-Path (Join-Path $x 'fifa15.exe')){Write-Output $x;break}}"`) do set "GAME=%%G"
if not defined GAME set /p "GAME=FIFA 15 folder containing fifa15.exe: "
set "BACKUP=%LOCALAPPDATA%\FIFA15LocalFUT\install-backup"
if not exist "%BACKUP%" (
  echo No installer backup was found.
  pause
  exit /b 1
)
copy /y "%BACKUP%\*" "%GAME%\" >nul
if exist "%BACKUP%\dlc_CardsDLL\CardsDLLzf.dll" (
  if exist "%GAME%\dlc\dlc_CardsDLL\dlc" copy /y "%BACKUP%\dlc_CardsDLL\CardsDLLzf.dll" "%GAME%\dlc\dlc_CardsDLL\dlc\CardsDLLzf.dll" >nul
)
if exist "%GAME%\STOP_LOCAL_FUT15.cmd" call "%GAME%\STOP_LOCAL_FUT15.cmd" /quiet >nul 2>nul
echo Backed-up files restored to %GAME%.
pause
