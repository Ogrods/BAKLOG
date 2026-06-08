# BAKLOG full data backup — library JSON, personal data, cache, .env.
# Code is in git; this captures everything gitignored that the app needs to restore.
#
# Usage (from repo root):
#   .\scripts\full_backup.ps1
#   .\scripts\full_backup.ps1 -Destination "D:\Backups"
#   .\scripts\full_backup.ps1 -RetentionDays 14
#   .\scripts\full_backup.ps1 -IncludeBrowserProfiles
#
param(
    [string]$Destination = "",
    [int]$RetentionDays = 30,
    [switch]$IncludeBrowserProfiles
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

# Sweep stale staging dirs from prior aborted runs.
Get-ChildItem -Path $env:TEMP -Filter "baklog-full-*" -Directory -ErrorAction SilentlyContinue |
    ForEach-Object {
        Remove-Item $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
    }

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

function Copy-Cache($includeBrowserProfiles) {
    $src = Join-Path $RepoRoot "cache"
    if (-not (Test-Path $src)) { return }
    $dest = Join-Path $staging "cache"
    New-Item -ItemType Directory -Force -Path $dest | Out-Null

    $robocopyArgs = @($src, $dest, "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/R:1", "/W:1")
    if (-not $includeBrowserProfiles) {
        $robocopyArgs += @("/XD", "auth", "screenshot-profile")
    }
    & robocopy.exe @robocopyArgs | Out-Null
    # Robocopy exit codes 0-7 are success (0 = nothing copied, 1 = files copied, etc.).
    if ($LASTEXITCODE -ge 8) {
        throw "robocopy cache copy failed with exit code $LASTEXITCODE"
    }
}

try {
    # Library + deals (gitignored)
    Get-ChildItem -Path $RepoRoot -Filter "games*.json" -File | ForEach-Object {
        Copy-Item $_.FullName (Join-Path $staging $_.Name) -Force
    }
    Copy-IfExists "itad_prices.json"
    Copy-IfExists "broken_images.json"
    Copy-IfExists "still_missing_images.json"

    # Personal + rotated fetcher backups
    Copy-IfExists "data"

    # Enrichment caches (browser profiles excluded by default — regenerable via re-login)
    Copy-Cache -includeBrowserProfiles:$IncludeBrowserProfiles.IsPresent

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
    $profileNote = if ($IncludeBrowserProfiles.IsPresent) {
        "included (cache/auth, cache/screenshot-profile)"
    } else {
        "excluded (cache/auth, cache/screenshot-profile - re-login to restore)"
    }
    $manifest = @"
BAKLOG full data backup
Created: $(Get-Date -Format "o")
Repo:    $RepoRoot
Git:     $gitHead
Retention: keep archives newer than $RetentionDays days
Browser profiles: $profileNote
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
} finally {
    Remove-Item $staging -Recurse -Force -ErrorAction SilentlyContinue
}

$sizeMb = [math]::Round((Get-Item $archivePath).Length / 1MB, 2)

# Prune archives older than RetentionDays.
$cutoff = (Get-Date).AddDays(-$RetentionDays)
$pruned = @()
Get-ChildItem $Destination -Filter "baklog-full-*.zip" -File -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt $cutoff } |
    ForEach-Object {
        $pruned += $_
        Remove-Item $_.FullName -Force
    }
$prunedMb = [math]::Round(($pruned | Measure-Object Length -Sum).Sum / 1MB, 2)

Write-Host ""
Write-Host "Full backup written:" -ForegroundColor Green
Write-Host "  $archivePath"
Write-Host "  $sizeMb MB"
Write-Host "  Retention: $RetentionDays days"
Write-Host "  Browser profiles: $(if ($IncludeBrowserProfiles.IsPresent) { 'included' } else { 'excluded (default)' })"
if ($pruned.Count -gt 0) {
    Write-Host "  Pruned $($pruned.Count) old archive(s), reclaimed $prunedMb MB" -ForegroundColor DarkGray
    foreach ($item in $pruned) {
        Write-Host "    - $($item.Name)" -ForegroundColor DarkGray
    }
} else {
    Write-Host "  Pruned 0 old archive(s)"
}
Write-Host ""
Write-Host "This archive may contain secrets (.env$(if (-not $IncludeBrowserProfiles.IsPresent) { ', cache metadata' } else { ', cache/auth' })). Store it safely." -ForegroundColor Yellow
