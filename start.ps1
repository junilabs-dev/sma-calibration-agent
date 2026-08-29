<#
    Start everything and verify it actually came up.

    Three processes, because each is a genuinely separate server:
      :8000  server.py         MCP tools -- what TrueForge connects to
      :8001  dashboard_api.py  the dashboard + its data feed (one origin)
      :8790  TrueForge         the harness UI

    You only ever open two of those: 8001 and 8790. 8000 is machine-to-machine.

    Logs go to .logs\. Stop everything with .\stop.ps1
#>

param([switch]$NoBrowser)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$py   = Join-Path $root '.venv\Scripts\python.exe'
$logs = Join-Path $root '.logs'

# run_trueforge.ps1 honours TRUEFORGE_PORT, so the health check and the printed
# URL have to resolve it the same way -- otherwise a custom port starts fine and
# the launcher sits here failing a check against 8790.
$tfPort = if ($env:TRUEFORGE_PORT) { $env:TRUEFORGE_PORT } else { '8790' }

function Test-Port($port) {
    try { (Invoke-WebRequest "http://localhost:$port/" -TimeoutSec 3 -UseBasicParsing).StatusCode -gt 0 }
    catch { $null -ne $_.Exception.Response }   # a 404 still means something answered
}

function Start-Piece($name, $exe, $argList, $log) {
    Start-Process -FilePath $exe -ArgumentList $argList -WorkingDirectory $root `
        -WindowStyle Minimized -RedirectStandardOutput $log -RedirectStandardError "$log.err"
    Write-Host ("  started {0}" -f $name) -ForegroundColor DarkGray
}

# --- preflight ---------------------------------------------------------------
if (-not (Test-Path $py)) {
    Write-Host "Python env missing. Run:" -ForegroundColor Red
    Write-Host "  python -m venv .venv"
    Write-Host "  .\.venv\Scripts\python.exe -m pip install -r requirements.txt"
    exit 1
}
if (-not (Test-Path (Join-Path $root 'node_modules\@truefoundry\trueforge'))) {
    Write-Host "TrueForge missing. Run:  npm install" -ForegroundColor Red
    exit 1
}
New-Item -ItemType Directory -Force -Path $logs | Out-Null

Write-Host ""
Write-Host "starting..." -ForegroundColor Cyan

if (Test-Port 8000) { Write-Host "  :8000 already up" -ForegroundColor DarkGray }
else { Start-Piece 'server.py       (MCP tools)' $py 'server.py' "$logs\server.log" }

if (Test-Port 8001) { Write-Host "  :8001 already up" -ForegroundColor DarkGray }
else { Start-Piece 'dashboard_api.py (dashboard)' $py 'dashboard_api.py' "$logs\dashboard.log" }

if (Test-Port $tfPort) { Write-Host "  :$tfPort already up" -ForegroundColor DarkGray }
else {
    # The path contains spaces, so -File must arrive already quoted or pwsh
    # splits it and reports "'D:\micro' is not recognized".
    $tf = Join-Path $root 'run_trueforge.ps1'
    Start-Process -FilePath 'pwsh' -ArgumentList @('-NoProfile', '-File', "`"$tf`"") `
        -WorkingDirectory $root -WindowStyle Minimized `
        -RedirectStandardOutput "$logs\trueforge.log" -RedirectStandardError "$logs\trueforge.log.err"
    Write-Host "  started TrueForge      (harness)" -ForegroundColor DarkGray
}

# --- wait for health ---------------------------------------------------------
Write-Host ""
$checks = @(
    @{ name = 'MCP tools'; url = 'http://localhost:8000/mcp';      ok = { param($c) $c -in 400,405,406,200 } }
    @{ name = 'Dashboard'; url = 'http://localhost:8001/health';   ok = { param($c) $c -eq 200 } }
    @{ name = 'TrueForge'; url = "http://localhost:$tfPort/";      ok = { param($c) $c -eq 200 } }
)

$deadline = (Get-Date).AddSeconds(75)
$state = @{}
foreach ($c in $checks) { $state[$c.name] = $false }

while ((Get-Date) -lt $deadline -and ($state.Values -contains $false)) {
    foreach ($c in $checks) {
        if ($state[$c.name]) { continue }
        try {
            $code = (Invoke-WebRequest $c.url -TimeoutSec 3 -UseBasicParsing).StatusCode
        } catch {
            $code = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { 0 }
        }
        if (& $c.ok $code) { $state[$c.name] = $true }
    }
    if ($state.Values -contains $false) { Start-Sleep -Milliseconds 1200 }
}

Write-Host "status" -ForegroundColor Cyan
foreach ($c in $checks) {
    if ($state[$c.name]) { Write-Host ("  [ok]   {0}" -f $c.name) -ForegroundColor Green }
    else                 { Write-Host ("  [FAIL] {0}  -- see .logs\" -f $c.name) -ForegroundColor Red }
}

if ($state.Values -contains $false) {
    Write-Host ""
    Write-Host "Something did not come up. Check .logs\ for the reason." -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "  Dashboard   http://localhost:8001" -ForegroundColor Cyan
Write-Host "  TrueForge   http://localhost:$tfPort" -ForegroundColor Cyan
Write-Host ""
Write-Host "  stop with .\stop.ps1" -ForegroundColor DarkGray
Write-Host ""

if (-not $NoBrowser) {
    Start-Process 'http://localhost:8001'
    Start-Process "http://localhost:$tfPort"
}
