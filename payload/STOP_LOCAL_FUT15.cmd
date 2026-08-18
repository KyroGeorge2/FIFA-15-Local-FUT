@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { ($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe') -and $_.CommandLine -like '*localfut15*server.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>nul
del /q "%LOCALAPPDATA%\FIFA15LocalFUT\runtime_ports.json" >nul 2>nul
del /q "%LOCALAPPDATA%\FIFA15LocalFUT\startup_phase.txt" >nul 2>nul
del /q "%ProgramData%\FIFA15LocalFUT\runtime_ports.json" >nul 2>nul
if /i not "%~1"=="/quiet" (
  echo FIFA 15 Local FUT server stopped.
  pause
)
endlocal
