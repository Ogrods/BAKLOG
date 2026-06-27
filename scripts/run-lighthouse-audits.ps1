# Run Lighthouse on app (built + perf profile) and landing static page.
# Reports land in lighthouse/ (gitignored). Requires: npm i -g lighthouse OR npx lighthouse.
param(
    [switch]$SkipBuild,
    [string]$AppUrl = 'http://127.0.0.1:8765',
    [string]$LandingUrl = 'http://127.0.0.1:4000/landing/index.html'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$py = Join-Path $root '.venv\Scripts\python.exe'
$lighthouseDir = Join-Path $root 'lighthouse'
New-Item -ItemType Directory -Force -Path $lighthouseDir | Out-Null

$stamp = Get-Date -Format 'yyyy-MM-dd'
$appReport = Join-Path $lighthouseDir "app-$stamp.report.html"
$landingReport = Join-Path $lighthouseDir "landing-$stamp.report.html"

function Invoke-Lighthouse {
    param([string]$Url, [string]$Out)
    Write-Host "==> lighthouse $Url"
    npx --yes lighthouse $Url `
        --only-categories=performance,accessibility,best-practices `
        --output=html `
        --output-path=$Out `
        --quiet `
        --chrome-flags="--headless --no-sandbox"
    if ($LASTEXITCODE -ne 0) {
        Write-Error "lighthouse failed for $Url (exit $LASTEXITCODE)"
    }
    if (-not (Test-Path $Out)) {
        Write-Error "lighthouse report missing: $Out"
    }
}

# --- Landing (static) ---
$landingProc = Start-Process -FilePath $py -ArgumentList @('-m', 'http.server', '4000', '--directory', '.') -WorkingDirectory $root -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 2
try {
    Invoke-Lighthouse -Url $LandingUrl -Out $landingReport
} finally {
    if ($landingProc -and -not $landingProc.HasExited) {
        Stop-Process -Id $landingProc.Id -Force -ErrorAction SilentlyContinue
    }
}

# --- App (built + perf profile) ---
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

$server = Start-Process -FilePath $py -ArgumentList 'server.py' -WorkingDirectory $root -PassThru -WindowStyle Hidden
try {
    $deadline = (Get-Date).AddSeconds(45)
    $ready = $false
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -Uri "$AppUrl/api/config" -UseBasicParsing -TimeoutSec 2
            if ($r.StatusCode -eq 200) { $ready = $true; break }
        } catch {}
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) { Write-Error "App server not ready at $AppUrl" }
    Invoke-Lighthouse -Url $AppUrl -Out $appReport
} finally {
    if ($server -and -not $server.HasExited) {
        & $py scripts/stop_baklog.py 2>$null | Out-Null
        if (-not $server.HasExited) { Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue }
    }
}

Write-Host "Lighthouse reports:"
Write-Host "  $appReport"
Write-Host "  $landingReport"
