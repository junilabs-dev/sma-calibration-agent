<#
    Stop everything start.ps1 launched.

    Matching on a bare name like "server.py" would reach any process on the
    machine running a file with that name -- another checkout, an unrelated
    project, a second TrueForge. Every process started here is launched either
    from this directory's .venv or with this directory's script path on its
    command line, so the checkout path is what identifies them.
#>

$root = $PSScriptRoot
$stopped = 0

foreach ($procName in @('python.exe', 'node.exe', 'pwsh.exe')) {
    Get-CimInstance Win32_Process -Filter "Name='$procName'" -ErrorAction SilentlyContinue |
        Where-Object {
            $cl = $_.CommandLine
            $cl -and $cl.Contains($root) -and $cl -notlike '*stop.ps1*'
        } |
        ForEach-Object {
            Write-Host ("  stopping {0} (pid {1})" -f $procName, $_.ProcessId) -ForegroundColor DarkGray
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            $script:stopped++
        }
}

if ($stopped -eq 0) { Write-Host "nothing running from $root" -ForegroundColor DarkGray }
else { Write-Host "stopped $stopped process(es)" -ForegroundColor Green }
