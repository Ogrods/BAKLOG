# Capture README / social screenshots from the fictional demo profile.
# Runs an isolated server (own BAKLOG_DATA_DIR + port) so the live profile,
# its data, and any dev server on 8765 are untouched.
param(
    [int]$Port = 8766,
    [string]$Views = 'dashboard,library,wishlist,connections',
    [string]$DataDir = (Join-Path $env:TEMP 'baklog-demo-data')
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$py = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { Write-Error "Missing $py - create .venv first." }

if (Test-Path $DataDir) { Remove-Item -Recurse -Force $DataDir }

Write-Host "==> generating demo profile in $DataDir"
node scripts/generate-demo-profile.mjs --data-dir $DataDir
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$baseUrl = "http://127.0.0.1:$Port"
$env:BAKLOG_DATA_DIR = $DataDir
$env:PORT = "$Port"
$env:BAKLOG_AUTH_DISABLED = '1'
$env:BAKLOG_ADMIN = '0'
$env:BAKLOG_IDLE_SHUTDOWN_MINUTES = '5'
$env:BAKLOG_NO_BROWSER = '1'

Write-Host "==> starting capture server on $baseUrl"
$server = Start-Process -FilePath $py -ArgumentList 'server.py' -WorkingDirectory $root -PassThru -WindowStyle Hidden

try {
    $deadline = (Get-Date).AddSeconds(40)
    $ready = $false
    while ((Get-Date) -lt $deadline) {
        try {
            if ((Invoke-WebRequest -Uri "$baseUrl/api/config" -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200) {
                $ready = $true; break
            }
        } catch { Start-Sleep -Milliseconds 400 }
    }
    if (-not $ready) { Write-Error "Capture server did not become ready at $baseUrl" }

    Write-Host "==> capturing views: $Views"
    node scripts/capture-screenshots.mjs $baseUrl --views $Views
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    # Keep the repo-root hero (README top, social embeds) on the same sample set.
    $gallery = Join-Path $root 'assets\screenshots\dashboard.png'
    if (Test-Path $gallery) {
        Copy-Item -Force $gallery (Join-Path $root 'dashboard.png')
        Write-Host '==> refreshed dashboard.png hero'
    }
    exit 0
} finally {
    if ($server -and -not $server.HasExited) {
        Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
    }
}
