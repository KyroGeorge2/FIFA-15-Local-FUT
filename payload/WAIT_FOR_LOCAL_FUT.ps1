<#
    FIFA 15 Local FUT - localhost readiness waiter.

    PLAY_LOCAL_FUT15.cmd used to poll with 30 iterations of a freshly spawned
    powershell.exe plus "timeout /t 1", which is only ~35s of real waiting on a
    fast machine and gave up long before a first-run server (dependency install,
    cold Python start, initial SQLite seeding) could come up. This waits on a
    real deadline inside one process, and reports *why* it gave up instead of a
    generic timeout.

    Exit codes consumed by PLAY_LOCAL_FUT15.cmd:
      0  ready
      1  timed out, no specific cause identified
      2  the server process died during startup
      3  port map was written under a different Windows profile
      4  port map exists but the FUT port refuses connections
      5  still installing Python dependencies when the deadline expired
#>
[CmdletBinding()]
param(
    [int] $TimeoutSeconds = 0
)

$ErrorActionPreference = 'Stop'

if ($TimeoutSeconds -le 0) {
    $configured = 0
    if ($env:LOCALFUT_WAIT_SECONDS -and [int]::TryParse($env:LOCALFUT_WAIT_SECONDS, [ref] $configured) -and $configured -gt 0) {
        $TimeoutSeconds = $configured
    } else {
        $TimeoutSeconds = 180
    }
}

$runtimeRoot = Join-Path $env:LOCALAPPDATA 'FIFA15LocalFUT'
$portsFile   = Join-Path $runtimeRoot 'runtime_ports.json'
$phaseFile   = Join-Path $runtimeRoot 'startup_phase.txt'
# Written as well by an elevated server so an elevation/profile split cannot
# hide the port map from this launcher.
$sharedPorts = Join-Path $env:ProgramData 'FIFA15LocalFUT\runtime_ports.json'

function Get-StartupPhase {
    if (-not (Test-Path $phaseFile)) { return '' }
    try { return (Get-Content $phaseFile -Raw -ErrorAction Stop).Trim() } catch { return '' }
}

function Get-FutPort {
    foreach ($candidate in @($portsFile, $sharedPorts)) {
        if (-not (Test-Path $candidate)) { continue }
        try {
            $raw = Get-Content $candidate -Raw -ErrorAction Stop
            if (-not $raw.Trim()) { continue }
            $port = [int] ($raw | ConvertFrom-Json).fut_port
            if ($port -gt 0) { return $port }
        } catch {
            # Half-written file: just retry on the next tick.
        }
    }
    return 0
}

function Test-FutPort {
    param([int] $Port)
    if ($Port -le 0) { return $false }
    $client = New-Object Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect('127.0.0.1', $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne(500)) { return $false }
        $client.EndConnect($async)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Test-ServerProcess {
    # Match on the command line, not just the image name: an unrelated Python
    # process must not stand in for server.py and mask its death (exit 2).
    try {
        $running = Get-CimInstance Win32_Process -ErrorAction Stop |
            Where-Object {
                ($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe') -and
                $_.CommandLine -like '*localfut15*server.py*'
            }
        return [bool] $running
    } catch {
        # If the CIM query is unavailable, fall back to the image-name check
        # rather than reporting the server as gone.
        return [bool] (Get-Process -Name python, pythonw, py -ErrorAction SilentlyContinue)
    }
}

function Find-ForeignPortsFile {
    try {
        $usersRoot = Split-Path $env:USERPROFILE -Parent
        foreach ($dir in (Get-ChildItem $usersRoot -Directory -ErrorAction SilentlyContinue)) {
            $candidate = Join-Path $dir.FullName 'AppData\Local\FIFA15LocalFUT\runtime_ports.json'
            if ((Test-Path $candidate) -and ($candidate -ne $portsFile)) { return $candidate }
        }
    } catch {
        # Profile enumeration is best effort; absence just means no extra hint.
    }
    return ''
}

Write-Host ("Waiting for localhost FUT service (up to {0}s)..." -f $TimeoutSeconds)

$started       = Get-Date
$deadline      = $started.AddSeconds($TimeoutSeconds)
$sawServerProc = $false
$missStreak    = 0
$lastNotice    = $started

while ((Get-Date) -lt $deadline) {
    $port = Get-FutPort
    if ($port -gt 0 -and (Test-FutPort $port)) {
        Write-Host ("Local FUT answered on 127.0.0.1:{0} after {1:N0}s." -f $port, ((Get-Date) - $started).TotalSeconds)
        exit 0
    }

    $phase = Get-StartupPhase

    if (Test-ServerProcess) {
        $sawServerProc = $true
        $missStreak = 0
    } elseif ($sawServerProc) {
        $missStreak++
    }

    # Only treat a vanished process as fatal once server.py itself was reached;
    # the dependency stage legitimately starts and stops short-lived pythons.
    if ($sawServerProc -and $missStreak -ge 10 -and $phase -ne 'deps') {
        Write-Host ''
        Write-Host 'The Local FUT server process exited during startup.'
        exit 2
    }

    if (((Get-Date) - $lastNotice).TotalSeconds -ge 5) {
        $lastNotice = Get-Date
        $elapsed = ((Get-Date) - $started).TotalSeconds
        if ($phase -eq 'deps') {
            $stage = 'installing Python dependencies'
        } elseif ($port -gt 0) {
            $stage = "port {0} not accepting connections yet" -f $port
        } elseif ($phase -eq 'server') {
            $stage = 'server starting (loading card database)'
        } else {
            $stage = 'server starting'
        }
        Write-Host ("  {0,3:N0}s - {1}" -f $elapsed, $stage)
    }

    Start-Sleep -Milliseconds 500
}

Write-Host ''

$phase = Get-StartupPhase
$port  = Get-FutPort

if ($port -gt 0) {
    Write-Host ("The port map names FUT port {0}, but 127.0.0.1:{0} refuses connections." -f $port)
    exit 4
}

$foreign = Find-ForeignPortsFile
if ($foreign) {
    Write-Host 'The server wrote its port map under a different Windows profile:'
    Write-Host ("  {0}" -f $foreign)
    Write-Host ("This launcher looked in: {0}" -f $portsFile)
    exit 3
}

if ($phase -eq 'deps') {
    Write-Host 'The server is still installing Python dependencies.'
    exit 5
}

exit 1
