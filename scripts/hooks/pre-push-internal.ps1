# Pre-push internal sync helper - runs from scripts/hooks/pre-push.
# Syncs gitignored internal paths to baklog-internal when they changed since last sync.
param(
    [string]$InternalRepo = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$manifestFile = Join-Path $RepoRoot "scripts\internal-manifest.txt"
$syncScript = Join-Path $RepoRoot "scripts\sync-internal-repo.ps1"

if (-not $InternalRepo) {
    $InternalRepo = Join-Path (Split-Path $RepoRoot -Parent) "baklog-internal"
}

if (-not (Test-Path $manifestFile)) {
    Write-Host "[pre-push] No internal manifest - skipping internal sync." -ForegroundColor DarkGray
    exit 0
}

$paths = Get-Content $manifestFile | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#")) { return }
    $line
} | Where-Object { $_ }

$lastSync = $null
$syncManifest = Join-Path $InternalRepo "SYNC-MANIFEST.txt"
if (Test-Path $syncManifest) {
    $content = Get-Content $syncManifest -Raw
    if ($content -match "Synced:\s+(\S+)") {
        try { $lastSync = [datetime]::Parse($Matches[1]) } catch { }
    }
}

$needsSync = $false
if (-not $lastSync) {
    $needsSync = $true
} else {
    foreach ($rel in $paths) {
        $src = Join-Path $RepoRoot $rel
        if (-not (Test-Path $src)) { continue }
        $item = Get-Item $src
        $newest = if ($item.PSIsContainer) {
            (Get-ChildItem $src -Recurse -File -ErrorAction SilentlyContinue |
                Sort-Object LastWriteTime -Descending |
                Select-Object -First 1).LastWriteTime
        } else {
            $item.LastWriteTime
        }
        if ($newest -and $newest -gt $lastSync) {
            $needsSync = $true
            break
        }
    }
}

if (-not $needsSync) {
    Write-Host "[pre-push] Internal docs unchanged since last sync - skipping." -ForegroundColor DarkGray
    exit 0
}

Write-Host "[pre-push] Internal docs changed - syncing to private repo..." -ForegroundColor Cyan
& $syncScript -InternalRepo $InternalRepo -Push
if ($LASTEXITCODE -ne 0) {
    Write-Host "[pre-push] Internal sync failed. Push aborted." -ForegroundColor Red
    exit 1
}
Write-Host "[pre-push] Internal sync complete." -ForegroundColor Green
exit 0
