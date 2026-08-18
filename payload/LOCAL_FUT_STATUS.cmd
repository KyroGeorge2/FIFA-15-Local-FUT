@echo off
setlocal EnableExtensions
title FIFA 15 Local FUT Status v0.2.39 Public Test 1
echo ============================================================
echo  FIFA 15 LOCAL FUT - SERVICE STATUS
echo ============================================================
powershell -NoProfile -ExecutionPolicy Bypass -Command "$f=Join-Path $env:LOCALAPPDATA 'FIFA15LocalFUT\runtime_ports.json'; if(-not (Test-Path $f)){$f=Join-Path $env:ProgramData 'FIFA15LocalFUT\runtime_ports.json'}; if(Test-Path $f){Write-Host ('Port map: '+$f); $x=Get-Content $f -Raw|ConvertFrom-Json; $ports=@($x.lsx_port,$x.redirect_port,$x.blaze_port,$x.qos_port,$x.easw_port,$x.fut_port,$x.legacy_fut_port); if($x.PSObject.Properties.Name -contains 'lsx_mode'){Write-Host ('LSX mode: '+$x.lsx_mode)}}else{Write-Host 'Port map: not found (server not running); probing default ports'; $ports=3216,42230,10051,17502,42232,8199,8099}; foreach($p in $ports){$c=Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if($c){$pr=Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue; Write-Host ('OK   127.0.0.1:'+$p+'  PID '+$c.OwningProcess+' '+$pr.ProcessName)}else{Write-Host ('MISS 127.0.0.1:'+$p)}}"
echo.
pause
