# BAKLOG full data backup — library JSON, personal data, cache, .env.
# Code is in git; this captures everything gitignored that the app needs to restore.
#
# Usage (from repo root):
#   .\scripts\full_backup.ps1
#   .\scripts\full_backup.ps1 -Destination "D:\Backups"
#
param(
    [string]$Destination = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $Destination) {
    $Destination = Join-Path (Split-Path $RepoRoot -Parent) "baklog-backups"
}
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$staging = Join-Path $env:TEMP "baklog-full-$stamp"
$archiveName = "baklog-full-$stamp.zip"
$archivePath = Join-Path $Destination $archiveName

New-Item -ItemType Directory -Force -Path $staging, $Destination | Out-Null

function Copy-IfExists($rel) {
    $src = Join-Path $RepoRoot $rel
    if (-not (Test-Path $src)) { return }
    $dest = Join-Path $staging $rel
    $parent = Split-Path $dest -Parent
    if ($parent -and -not (Test-Path $parent)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    if ((Get-Item $src).PSIsContainer) {
        Copy-Item -Path $src -Destination $dest -Recurse -Force
    } else {
        Copy-Item -Path $src -Destination $dest -Force
    }
}

# Library + deals (gitignored)
Get-ChildItem -Path $RepoRoot -Filter "games*.json" -File | ForEach-Object {
    Copy-Item $_.FullName (Join-Path $staging $_.Name) -Force
}
Copy-IfExists "itad_prices.json"
Copy-IfExists "broken_images.json"
Copy-IfExists "still_missing_images.json"

# Personal + rotated fetcher backups
Copy-IfExists "data"

# Enrichment caches, run queue, auth profiles
Copy-IfExists "cache"

# Local credentials (plaintext fallback — treat archive as secret)
Copy-IfExists ".env"

# Manifest
$gitHead = ""
try {
    Push-Location $RepoRoot
    $gitHead = (git rev-parse --short HEAD 2>$null)
    if (-not $gitHead) { $gitHead = "unknown" }
} finally {
    Pop-Location
}
$manifest = @"
BAKLOG full data backup
Created: $(Get-Date -Format "o")
Repo:    $RepoRoot
Git:     $gitHead
Contents: games_*.json, itad_prices.json, data/, cache/, .env (if present)
Restore:  unzip into a fresh clone at the same paths; re-run fetchers as needed.
"@
Set-Content -Path (Join-Path $staging "BACKUP-MANIFEST.txt") -Value $manifest -Encoding UTF8

if (Test-Path $archivePath) { Remove-Item $archivePath -Force }
# Compress-Archive chokes on some cache files with out-of-range timestamps; tar is reliable on Win10+.
Push-Location $staging
try {
    & tar.exe -a -cf $archivePath *
    if ($LASTEXITCODE -ne 0) { throw "tar exited with code $LASTEXITCODE" }
} finally {
    Pop-Location
}
Remove-Item $staging -Recurse -Force

$sizeMb = [math]::Round((Get-Item $archivePath).Length / 1MB, 2)
Write-Host ""
Write-Host "Full backup written:" -ForegroundColor Green
Write-Host "  $archivePath"
Write-Host "  $sizeMb MB"
Write-Host ""
Write-Host "This archive may contain secrets (.env, cache/auth). Store it safely." -ForegroundColor Yellow
