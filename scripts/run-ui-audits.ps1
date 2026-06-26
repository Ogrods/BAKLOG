# Sync perf profile, start built server, run Playwright UI audits, stop server.
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

$fixturePerf = Join-Path $root 'tests\fixtures\perf-profile\perf'
$destPerf = Join-Path $root 'profiles\perf'
if (-not (Test-Path $fixturePerf)) {
    node scripts/generate-perf-profile.mjs
}
New-Item -ItemType Directory -Force -Path $destPerf | Out-Null
Copy-Item -Recurse -Force (Join-Path $fixturePerf '*') $destPerf

if (-not $SkipBuild) {
    Write-Host '==> npm run build'
    npm run build
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$env:BAKLOG_PROFILE = 'perf'
$env:BAKLOG_SERVE_BUILT = '1'
$env:BAKLOG_ADMIN = '0'
$env:BAKLOG_AUTH_DISABLED = '1'

Write-Host '==> starting server for UI audits (BAKLOG_PROFILE=perf)'
$server = Start-Process -FilePath $py -ArgumentList 'server.py' -WorkingDirectory $root -PassThru -WindowStyle Hidden

function Stop-Server {
    if ($server -and -not $server.HasExited) {
        & $py scripts/stop_baklog.py 2>$null | Out-Null
        if (-not $server.HasExited) { Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue }
    }
}

try {
    $deadline = (Get-Date).AddSeconds(45)
    $ready = $false
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -Uri "$BaseUrl/api/config" -UseBasicParsing -TimeoutSec 2
            if ($r.StatusCode -eq 200) { $ready = $true; break }
        } catch {}
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) {
        Write-Error "Server did not become ready at $BaseUrl"
    }

    Write-Host '==> npm run audit:ui'
    npm run audit:ui -- $BaseUrl
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
    Stop-Server
}

Write-Host 'UI audits passed.'
