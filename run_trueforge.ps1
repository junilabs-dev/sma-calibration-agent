<#
    Launch TrueForge scoped entirely to this folder.

    TrueForge otherwise keeps its SQLite database and its sandbox working
    directories under the OS-wide app-data location (on Windows that is
    %LOCALAPPDATA%\trueforge\Data). Nothing here is global: the SQLITE_PATH
    override moves the database, and redirecting LOCALAPPDATA / XDG_DATA_HOME
    moves everything else that TrueForge resolves through env-paths -- notably
    the sandbox root, which has no override of its own.

    Everything lands in .trueforge-local\, so deleting that folder is a full
    reset and nothing outside this project is touched.
#>

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$state = Join-Path $root '.trueforge-local'

New-Item -ItemType Directory -Force -Path $state | Out-Null

$env:LOCALAPPDATA  = $state   # env-paths data root -> sandboxes, default db
$env:XDG_DATA_HOME = $state   # same, for macOS/Linux
$env:SQLITE_PATH   = Join-Path $state 'db\db.sqlite'
$env:PORT          = if ($env:TRUEFORGE_PORT) { $env:TRUEFORGE_PORT } else { '8790' }

$cli = Join-Path $root 'node_modules\@truefoundry\trueforge\dist\cli.js'
if (-not (Test-Path $cli)) {
    Write-Error "TrueForge is not installed locally. Run: npm install"
}

Write-Host "TrueForge state : $state"  -ForegroundColor DarkGray
Write-Host "TrueForge UI    : http://localhost:$($env:PORT)" -ForegroundColor Cyan
Write-Host ""

node $cli
