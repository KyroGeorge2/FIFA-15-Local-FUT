@echo off
setlocal EnableExtensions
cd /d "%~dp0"
call "%~dp0STOP_LOCAL_FUT15.cmd" /quiet >nul 2>nul

echo ============================================================
echo  RESET FIFA 15 LOCAL FUT TO PUBLIC-TEST STARTER CLUB
echo ============================================================
echo  WARNING: This deletes your LOCAL FUT club/save.
echo  It does not touch normal FIFA 15 Career/Settings saves.
echo.
set /p "OK=Type RESET to continue: "
if /I not "%OK%"=="RESET" exit /b 0

set "ROOTSTATE=%LOCALAPPDATA%\FIFA15LocalFUT"
set "LEGACY=%ROOTSTATE%\data"
for %%F in (
    "%ROOTSTATE%\fut15-local.sqlite3"
    "%ROOTSTATE%\fut15-local.sqlite3-wal"
    "%ROOTSTATE%\fut15-local.sqlite3-shm"
    "%LEGACY%\localfut15.sqlite3"
    "%LEGACY%\localfut15.sqlite3-wal"
    "%LEGACY%\localfut15.sqlite3-shm"
) do if exist "%%~F" del /f /q "%%~F"

echo.
echo Reset complete. The next Local FUT launch will create the barebones
 echo bronze starter club from this public-test build.
echo.
pause
