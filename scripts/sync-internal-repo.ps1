# Sync gitignored internal docs (marketing, licensing leads, etc.) to a private repo.
# Does NOT copy .env, data/, cache/, or games_*.json — use full_backup.ps1 for personal data.
#
# One-time setup:
#   1. Create a private GitHub repo (e.g. baklog-internal).
#   2. Clone it as a sibling: ../baklog-internal next to this repo.
#   3. Run: .\scripts\sync-internal-repo.ps1
#
# Usage (from repo root):
#   .\scripts\sync-internal-repo.ps1
#   .\scripts\sync-internal-repo.ps1 -InternalRepo "D:\repos\baklog-internal" -Push
#   .\scripts\sync-internal-repo.ps1 -NoCommit
#
param(
    [string]$InternalRepo = "",
    [string]$Message = "",
    [switch]$Push,
    [switch]$NoCommit
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $InternalRepo) {
    $InternalRepo = Join-Path (Split-Path $RepoRoot -Parent) "baklog-internal"
}
if (Test-Path -LiteralPath $InternalRepo) {
    $InternalRepo = (Resolve-Path -LiteralPath $InternalRepo).Path
} else {
    New-Item -ItemType Directory -Force -Path $InternalRepo | Out-Null
    $InternalRepo = (Resolve-Path -LiteralPath $InternalRepo).Path
}

$manifestFile = Join-Path $PSScriptRoot "internal-manifest.txt"
if (-not (Test-Path $manifestFile)) {
    Write-Error "Missing manifest: $manifestFile"
}

function Copy-InternalPath($rel) {
    $src = Join-Path $RepoRoot $rel
    if (-not (Test-Path $src)) { return $false }
    $dest = Join-Path $InternalRepo $rel
    $parent = Split-Path $dest -Parent
    if ($parent -and -not (Test-Path $parent)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    if ((Get-Item $src).PSIsContainer) {
        if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
        Copy-Item -Path $src -Destination $dest -Recurse -Force
    } else {
        Copy-Item -Path $src -Destination $dest -Force
    }
    return $true
}

$paths = Get-Content $manifestFile | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#")) { return }
    $line
} | Where-Object { $_ }

$copied = @()
foreach ($rel in $paths) {
    if (Copy-InternalPath $rel) { $copied += $rel }
}

$gitHead = "unknown"
try {
    Push-Location $RepoRoot
    $out = git rev-parse --short HEAD 2>$null
    if ($out) { $gitHead = $out.Trim() }
} finally {
    Pop-Location
}

$syncManifest = @"
BAKLOG internal docs sync
Synced:   $(Get-Date -Format "o")
Source:   $RepoRoot
Git HEAD: $gitHead
Copied:   $($copied -join ", ")
"@
Set-Content -Path (Join-Path $InternalRepo "SYNC-MANIFEST.txt") -Value $syncManifest -Encoding UTF8

$readmePath = Join-Path $InternalRepo "README.md"
if (-not (Test-Path $readmePath)) {
    $seed = @'
# BAKLOG internal (private)

This repository holds gitignored internal documents synced from the public
steam-backlog repo (marketing, licensing leads, audits, etc.).

- Not deployed: only landing/ is public on Vercel (baklog.app).
- Do not publish this repo or its contents.

## Sync from your machine

From the public repo root:

  .\scripts\sync-internal-repo.ps1 -Push

Paths are listed in scripts/internal-manifest.txt in the public repo.
'@
    Set-Content -Path $readmePath -Value $seed -Encoding UTF8
}

Write-Host ""
Write-Host "Internal sync:" -ForegroundColor Green
Write-Host "  Destination: $InternalRepo"
if ($copied.Count -gt 0) {
    Write-Host "  Copied:      $($copied -join ', ')"
} else {
    Write-Host "  Copied:      (none - manifest paths missing locally)" -ForegroundColor Yellow
}

if ($NoCommit) {
    Write-Host "  Commit:      skipped (-NoCommit)" -ForegroundColor Yellow
    exit 0
}

$isGit = Test-Path (Join-Path $InternalRepo ".git")
if (-not $isGit) {
    Write-Host ""
    Write-Host "Destination is not a git repo. Clone your private GitHub repo there, then re-run." -ForegroundColor Yellow
    Write-Host "  git init; git remote add origin YOUR-PRIVATE-REPO-URL" -ForegroundColor DarkGray
    exit 0
}

if (-not $Message) {
    $Message = "sync internal docs from steam-backlog at $gitHead"
}

Push-Location $InternalRepo
try {
    git add -A
    $status = git status --porcelain
    if (-not $status) {
        Write-Host "  Commit:      nothing to commit (already up to date)" -ForegroundColor DarkGray
    } else {
        git commit -m $Message
        Write-Host "  Commit:      $Message" -ForegroundColor Green
    }
    if ($Push) {
        git push 2>$null
        if ($LASTEXITCODE -ne 0) {
            git push -u origin HEAD
            if ($LASTEXITCODE -ne 0) { throw "git push failed" }
        }
        Write-Host "  Push:        done" -ForegroundColor Green
    }
} finally {
    Pop-Location
}

Write-Host ""
