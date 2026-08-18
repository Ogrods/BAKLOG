# Sync perf profile fixture, start server, run Playwright perf audit, stop server.
param(
    [switch]$SkipBuild,
    [string]$BaseUrl = 'http://127.0.0.1:8765'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$py = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) {
    Write-Error "Missing $py - create .venv first."
}

Write-Host '==> generate + sync perf profile fixture (index active=perf)'
node scripts/generate-perf-profile.mjs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$fixtureRoot = Join-Path $root 'tests\fixtures\perf-profile'
$profilesDir = Join-Path $root 'profiles'
$destPerf = Join-Path $profilesDir 'perf'
New-Item -ItemType Directory -Force -Path $destPerf | Out-Null
Copy-Item -Force (Join-Path $fixtureRoot 'index.json') (Join-Path $profilesDir 'index.json')
Copy-Item -Recurse -Force (Join-Path $fixtureRoot 'perf\*') $destPerf

if (-not $SkipBuild) {
    Write-Host '==> npm run build'
    npm run build
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$env:BAKLOG_PROFILE = 'perf'
$env:BAKLOG_SERVE_BUILT = '1'
$env:BAKLOG_ADMIN = '0'
$env:BAKLOG_AUTH_DISABLED = '1'

Write-Host '==> starting server (profiles/index.json active=perf, BAKLOG_SERVE_BUILT=1, AUTH_DISABLED)'
$server = Start-Process -FilePath $py -ArgumentList 'server.py' -WorkingDirectory $root -PassThru -WindowStyle Hidden

function Stop-Server {
    if ($server -and -not $server.HasExited) {
        & $py scripts/stop_baklog.py 2>$null | Out-Null
        if (-not $server.HasExited) { Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue }
    }
}

try {
    $deadline = (Get-Date).AddSeconds(30)
    $ready = $false
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -Uri "$BaseUrl/api/config" -UseBasicParsing -TimeoutSec 2
            if ($r.StatusCode -eq 200) { $ready = $true; break }
        } catch { Start-Sleep -Milliseconds 400 }
    }
    if (-not $ready) {
        Write-Error "Server did not become ready at $BaseUrl"
    }

    Write-Host '==> perf audit'
    node scripts/perf-audit.mjs $BaseUrl
    exit $LASTEXITCODE
} finally {
    Stop-Server
}
