<#
    Stop everything start.ps1 launched.

    Matches on command line rather than killing every python/node on the box,
    so unrelated work on this machine is left alone.
#>

$root = $PSScriptRoot
$patterns = @('server.py', 'dashboard_api.py', 'trueforge')
$stopped = 0

foreach ($procName in @('python.exe', 'node.exe', 'pwsh.exe')) {
    Get-CimInstance Win32_Process -Filter "Name='$procName'" -ErrorAction SilentlyContinue |
        Where-Object {
            $cl = $_.CommandLine
            $cl -and ($patterns | Where-Object { $cl -like "*$_*" }) -and $cl -notlike '*stop.ps1*'
        } |
        ForEach-Object {
            Write-Host ("  stopping {0} (pid {1})" -f $procName, $_.ProcessId) -ForegroundColor DarkGray
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            $script:stopped++
        }
}

if ($stopped -eq 0) { Write-Host "nothing running" -ForegroundColor DarkGray }
else { Write-Host "stopped $stopped process(es)" -ForegroundColor Green }
