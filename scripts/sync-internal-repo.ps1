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
# Safety (do not weaken — this script runs from the public pre-push hook):
#   Git hooks set GIT_DIR / GIT_WORK_TREE / GIT_INDEX_FILE to the repo being
#   pushed. A cd into baklog-internal does NOT retarget git; `git add -A` and
#   `git commit` would stage the private tree into the public repo. Always
#   Clear-InheritedGitEnv, then `git -C $InternalRepo`, then confirm the public
#   HEAD SHA did not move (reset it if it did). Directory copies merge; they
#   never delete dest-only files such as .cursor/rules/internal-*.mdc.
#
param(
    [string]$InternalRepo = "",
    [string]$RepoRoot = "",
    [string]$ManifestFile = "",
    [string]$Message = "",
    [switch]$Push,
    [switch]$NoCommit
)

$ErrorActionPreference = "Stop"

function Clear-InheritedGitEnv {
    @(
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_NAMESPACE",
        "GIT_COMMON_DIR",
        "GIT_PREFIX",
        "GIT_SUPER_PREFIX"
    ) | ForEach-Object {
        if (Test-Path "Env:$_") { Remove-Item "Env:$_" }
    }
}

function Invoke-GitAt {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string[]]$GitArgs
    )
    Clear-InheritedGitEnv
    $output = & git -C $Path @GitArgs 2>&1
    return [pscustomobject]@{
        Code   = $LASTEXITCODE
        Output = $output
        Text   = (($output | ForEach-Object { "$_" }) -join "`n").Trim()
    }
}

function Get-RepoToplevel([string]$Path) {
    $r = Invoke-GitAt -Path $Path -GitArgs @("rev-parse", "--show-toplevel")
    if ($r.Code -ne 0 -or -not $r.Text) {
        throw "Not a git work tree: $Path"
    }
    return (Resolve-Path -LiteralPath $r.Text).Path.TrimEnd("\", "/")
}

function Get-OriginUrl([string]$Path) {
    $r = Invoke-GitAt -Path $Path -GitArgs @("remote", "get-url", "origin")
    if ($r.Code -ne 0) { return "" }
    return $r.Text
}

function Get-HeadSha([string]$Path) {
    $r = Invoke-GitAt -Path $Path -GitArgs @("rev-parse", "HEAD")
    if ($r.Code -ne 0 -or -not $r.Text) {
        throw "Could not read HEAD in $Path"
    }
    return $r.Text
}

function Normalize-RepoPath([string]$Path) {
    return (Resolve-Path -LiteralPath $Path).Path.TrimEnd("\", "/").ToLowerInvariant()
}

function Assert-SafeInternalDestination([string]$SourceRoot, [string]$DestRoot) {
    $srcTop = Get-RepoToplevel $SourceRoot
    $dstTop = Get-RepoToplevel $DestRoot
    if ((Normalize-RepoPath $srcTop) -eq (Normalize-RepoPath $dstTop)) {
        throw "Refusing internal sync: destination is the same git work tree as the public repo ($srcTop)."
    }
    $srcUrl = Get-OriginUrl $SourceRoot
    $dstUrl = Get-OriginUrl $DestRoot
    if (-not $dstUrl) {
        throw "Refusing internal sync: $DestRoot has no origin remote."
    }
    if ($dstUrl -notmatch "baklog-internal") {
        throw "Refusing internal sync: origin '$dstUrl' is not baklog-internal."
    }
    if ($srcUrl -and ($srcUrl.TrimEnd("/") -ieq $dstUrl.TrimEnd("/"))) {
        throw "Refusing internal sync: public and internal remotes are identical ($srcUrl)."
    }
    if ($dstUrl -match "Ogrods/BAKLOG(\.git)?/?$") {
        throw "Refusing internal sync: origin looks like the public BAKLOG repo ($dstUrl)."
    }
}

function Copy-InternalPath([string]$RepoRoot, [string]$InternalRepo, [string]$rel) {
    $src = Join-Path $RepoRoot $rel
    if (-not (Test-Path -LiteralPath $src)) { return $false }
    $dest = Join-Path $InternalRepo $rel
    $srcItem = Get-Item -LiteralPath $src
    if ($srcItem.PSIsContainer) {
        if (-not (Test-Path -LiteralPath $dest)) {
            New-Item -ItemType Directory -Force -Path $dest | Out-Null
        }
        $srcRoot = $srcItem.FullName.TrimEnd("\", "/")
        Get-ChildItem -LiteralPath $src -Recurse -File -Force | ForEach-Object {
            $relFile = $_.FullName.Substring($srcRoot.Length).TrimStart("\", "/")
            $destFile = Join-Path $dest $relFile
            $destParent = Split-Path $destFile -Parent
            if ($destParent -and -not (Test-Path -LiteralPath $destParent)) {
                New-Item -ItemType Directory -Force -Path $destParent | Out-Null
            }
            Copy-Item -LiteralPath $_.FullName -Destination $destFile -Force
        }
    } else {
        $parent = Split-Path $dest -Parent
        if ($parent -and -not (Test-Path -LiteralPath $parent)) {
            New-Item -ItemType Directory -Force -Path $parent | Out-Null
        }
        Copy-Item -LiteralPath $src -Destination $dest -Force
    }
    return $true
}

if (-not $RepoRoot) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
} else {
    $RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
}
if (-not $InternalRepo) {
    $InternalRepo = Join-Path (Split-Path $RepoRoot -Parent) "baklog-internal"
}
if (-not (Test-Path -LiteralPath $InternalRepo)) {
    throw "Internal repo not found: $InternalRepo. Clone Ogrods/baklog-internal as a sibling, then re-run."
}
$InternalRepo = (Resolve-Path -LiteralPath $InternalRepo).Path

if (-not $ManifestFile) {
    $ManifestFile = Join-Path $PSScriptRoot "internal-manifest.txt"
}
if (-not (Test-Path -LiteralPath $ManifestFile)) {
    throw "Missing manifest: $ManifestFile"
}

if (-not (Test-Path -LiteralPath (Join-Path $InternalRepo ".git"))) {
    Write-Host ""
    Write-Host "Destination is not a git repo. Clone your private GitHub repo there, then re-run." -ForegroundColor Yellow
    Write-Host "  git clone https://github.com/Ogrods/baklog-internal.git `"$InternalRepo`"" -ForegroundColor DarkGray
    exit 0
}

Assert-SafeInternalDestination -SourceRoot $RepoRoot -DestRoot $InternalRepo
$publicHeadBefore = Get-HeadSha $RepoRoot

$paths = Get-Content -LiteralPath $ManifestFile | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#")) { return }
    $line
} | Where-Object { $_ }

$copied = @()
foreach ($rel in $paths) {
    if (Copy-InternalPath $RepoRoot $InternalRepo $rel) { $copied += $rel }
}

$headShort = Invoke-GitAt -Path $RepoRoot -GitArgs @("rev-parse", "--short", "HEAD")
$gitHead = if ($headShort.Code -eq 0 -and $headShort.Text) { $headShort.Text } else { "unknown" }

$syncManifest = @"
BAKLOG internal docs sync
Synced:   $(Get-Date -Format "o")
Source:   $RepoRoot
Git HEAD: $gitHead
Copied:   $($copied -join ", ")
"@
Set-Content -Path (Join-Path $InternalRepo "SYNC-MANIFEST.txt") -Value $syncManifest -Encoding UTF8

$readmePath = Join-Path $InternalRepo "README.md"
if (-not (Test-Path -LiteralPath $readmePath)) {
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

function Assert-PublicHeadUnchanged([string]$ExpectedHead) {
    $after = Get-HeadSha $RepoRoot
    if ($after -eq $ExpectedHead) { return }
    $reset = Invoke-GitAt -Path $RepoRoot -GitArgs @("reset", "--hard", $ExpectedHead)
    throw ("Internal sync committed to the public repo (inherited GIT_DIR). " +
        "Reset public HEAD $after -> $ExpectedHead (git reset --hard exit $($reset.Code)). Refusing to continue.")
}

if ($NoCommit) {
    Write-Host "  Commit:      skipped (-NoCommit)" -ForegroundColor Yellow
    Assert-PublicHeadUnchanged $publicHeadBefore
    exit 0
}

if (-not $Message) {
    $Message = "sync internal docs from steam-backlog at $gitHead"
}

$addArgs = @("add", "--", "SYNC-MANIFEST.txt", "README.md") + $copied
$add = Invoke-GitAt -Path $InternalRepo -GitArgs $addArgs
if ($add.Code -ne 0) {
    Assert-PublicHeadUnchanged $publicHeadBefore
    throw "git add in internal repo failed: $($add.Text)"
}

$status = Invoke-GitAt -Path $InternalRepo -GitArgs @("status", "--porcelain")
if (-not $status.Text) {
    Write-Host "  Commit:      nothing to commit (already up to date)" -ForegroundColor DarkGray
} else {
    $commit = Invoke-GitAt -Path $InternalRepo -GitArgs @("commit", "-m", $Message)
    if ($commit.Code -ne 0) {
        Assert-PublicHeadUnchanged $publicHeadBefore
        throw "git commit in internal repo failed: $($commit.Text)"
    }
    Write-Host "  Commit:      $Message" -ForegroundColor Green
}

Assert-PublicHeadUnchanged $publicHeadBefore

$internalTop = Get-RepoToplevel $InternalRepo
if ((Normalize-RepoPath $internalTop) -eq (Normalize-RepoPath (Get-RepoToplevel $RepoRoot))) {
    throw "Refusing to push: internal git toplevel collapsed onto the public repo."
}

if ($Push) {
    $pushResult = Invoke-GitAt -Path $InternalRepo -GitArgs @("push")
    if ($pushResult.Code -ne 0) {
        $pushResult = Invoke-GitAt -Path $InternalRepo -GitArgs @("push", "-u", "origin", "HEAD")
        if ($pushResult.Code -ne 0) {
            throw "git push of baklog-internal failed: $($pushResult.Text)"
        }
    }
    Write-Host "  Push:        done" -ForegroundColor Green
}

Write-Host ""
