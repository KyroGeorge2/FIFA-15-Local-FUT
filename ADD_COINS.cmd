@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if not exist "%~dp0payload\ADD_COINS.cmd" (
  echo ERROR: payload\ADD_COINS.cmd is missing.
  pause
  exit /b 1
)
call "%~dp0payload\ADD_COINS.cmd"
