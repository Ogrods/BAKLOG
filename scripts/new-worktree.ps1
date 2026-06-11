# Spin up an isolated git worktree for a parallel agent.
#
# One agent = one worktree = one single-purpose branch. Enforces the
# feat/ | fix/ | chore/ naming scheme and wires up .venv / node_modules so the
# new folder is immediately usable on Windows.
#
# Usage (from repo root):
#   .\scripts\new-worktree.ps1 feat/ads-polish
#   .\scripts\new-worktree.ps1 fix/itad-prices -From main
#   .\scripts\new-worktree.ps1 feat/affiliate-v2 -FreshVenv   # clean venv instead of a junction
#   .\scripts\new-worktree.ps1 chore/deps -NoLink             # skip .venv / node_modules linking
#
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Branch,
    [string]$From = "main",
    [switch]$FreshVenv,
    [switch]$NoLink
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ParentDir = Split-Path -Parent $RepoRoot
Set-Location $RepoRoot

# --- Validate branch name -------------------------------------------------
if ($Branch -notmatch '^(feat|fix|chore)/[a-z0-9][a-z0-9._-]*$') {
    Write-Host "Rejected branch name: '$Branch'" -ForegroundColor Red
    Write-Host "Use one concern per branch with a prefix: feat/ , fix/ , or chore/" -ForegroundColor Yellow
    Write-Host "  e.g. feat/pro-debug-url   (not 'pro-debug-url')" -ForegroundColor Yellow
    exit 1
}

$slug = ($Branch -replace '^(feat|fix|chore)/', '') -replace '[^a-zA-Z0-9._-]', '-'
$WorktreePath = Join-Path $ParentDir "baklog-$slug"

if (Test-Path $WorktreePath) {
    Write-Host "Path already exists: $WorktreePath" -ForegroundColor Red
    exit 1
}

$branchExists = (git branch --list $Branch)
if ($branchExists) {
    Write-Host "Branch '$Branch' already exists. Pick a fresh name or close the old worktree first." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "BAKLOG new-worktree" -ForegroundColor Cyan
Write-Host "  Branch:   $Branch (from $From)"
Write-Host "  Folder:   $WorktreePath"
Write-Host ""

# --- Refresh base + create the worktree -----------------------------------
Write-Host "--- Fetching origin ---" -ForegroundColor Cyan
git fetch origin --prune 2>$null

Write-Host "--- Creating worktree ---" -ForegroundColor Cyan
git worktree add -b $Branch $WorktreePath $From
if ($LASTEXITCODE -ne 0) {
    Write-Host "git worktree add failed." -ForegroundColor Red
    exit 1
}

# --- Wire up dependencies so the folder is usable -------------------------
if (-not $NoLink) {
    # .venv: a junction is instant and works because BAKLOG runs scripts from
    # the worktree root (sys.path[0] wins over the editable install path).
    $srcVenv = Join-Path $RepoRoot ".venv"
    $dstVenv = Join-Path $WorktreePath ".venv"
    if ($FreshVenv) {
        Write-Host "--- Building fresh .venv ---" -ForegroundColor Cyan
        py -3.13 -m venv $dstVenv
        & (Join-Path $dstVenv "Scripts\python.exe") -m pip install -e "$WorktreePath[dev]"
    } elseif (Test-Path $srcVenv) {
        Write-Host "--- Linking .venv (junction) ---" -ForegroundColor Cyan
        New-Item -ItemType Junction -Path $dstVenv -Value $srcVenv | Out-Null
    } else {
        Write-Host "No .venv to link (run: py -3.13 -m venv .venv; .\.venv\Scripts\pip install -e '.[dev]')" -ForegroundColor Yellow
    }

    # node_modules: junction the existing install so npm test works immediately.
    $srcNode = Join-Path $RepoRoot "node_modules"
    $dstNode = Join-Path $WorktreePath "node_modules"
    if (Test-Path $srcNode) {
        Write-Host "--- Linking node_modules (junction) ---" -ForegroundColor Cyan
        New-Item -ItemType Junction -Path $dstNode -Value $srcNode | Out-Null
    }
}

Write-Host ""
Write-Host "Worktree ready." -ForegroundColor Green
Write-Host "  cd `"$WorktreePath`""
Write-Host "  Point one agent here; keep it to this single concern."
Write-Host "  When merged:  .\scripts\close-worktree.ps1 $Branch"
Write-Host ""
git worktree list
