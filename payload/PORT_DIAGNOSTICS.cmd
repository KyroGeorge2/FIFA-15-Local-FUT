@echo off
setlocal EnableExtensions
title FIFA 15 Local FUT Port Diagnostics
echo ============================================================
echo  FIFA 15 LOCAL FUT - PORT DIAGNOSTICS
echo ============================================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ports=3216,42230,10051,17502,42232,8199,8099; foreach($p in $ports){$x=Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if($x){$pr=Get-Process -Id $x.OwningProcess -ErrorAction SilentlyContinue; Write-Host ('PORT '+$p+' : IN USE  PID '+$x.OwningProcess+'  '+$pr.ProcessName)}else{Write-Host ('PORT '+$p+' : no listening process')}}"
echo.
echo Windows excluded/reserved TCP ranges:
netsh interface ipv4 show excludedportrange protocol=tcp
echo.
echo NOTE: Port 3216 being IN USE by EADesktop/Origin is normal for this build.
echo Local FUT will use that existing LSX listener.
echo If 3216 has no listener but sits inside an excluded range, send this output.
echo.
pause
