# Tear down a worktree after its branch is squash-merged.
#
# Removes the worktree folder, deletes the local branch, deletes the remote
# branch, then prunes stale worktree + remote-tracking refs. This is the
# "always delete after merge" rule as one command.
#
# Usage (from repo root):
#   .\scripts\close-worktree.ps1 feat/ads-polish
#   .\scripts\close-worktree.ps1 feat/ads-polish -KeepRemote   # leave origin branch
#   .\scripts\close-worktree.ps1 feat/ads-polish -Force        # unmerged: force-delete
#   .\scripts\close-worktree.ps1 feat/ads-polish -DryRun       # show what would happen
#
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Branch,
    [switch]$KeepRemote,
    [switch]$Force,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

function Step($desc, $cmd) {
    if ($DryRun) {
        Write-Host "[dry-run] $desc" -ForegroundColor Yellow
        Write-Host "          $cmd" -ForegroundColor DarkGray
    } else {
        Write-Host "--- $desc ---" -ForegroundColor Cyan
        Invoke-Expression $cmd
    }
}

# --- Locate the worktree folder bound to this branch ----------------------
$WorktreePath = $null
$cur = $null
foreach ($line in (git worktree list --porcelain)) {
    if ($line -like "worktree *") { $cur = $line.Substring(9) }
    elseif ($line -like "branch *") {
        $ref = $line.Substring(7)   # refs/heads/<branch>
        if ($ref -eq "refs/heads/$Branch") { $WorktreePath = $cur }
    }
}

if ($WorktreePath -and ((Resolve-Path $WorktreePath).Path -eq $RepoRoot)) {
    Write-Host "Refusing to remove the primary worktree (you're on '$Branch' in the main folder)." -ForegroundColor Red
    Write-Host "Switch the main worktree to 'main' first." -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "BAKLOG close-worktree" -ForegroundColor Cyan
Write-Host "  Branch:   $Branch"
Write-Host "  Folder:   $(if ($WorktreePath) { $WorktreePath } else { '(no worktree found - branch only)' })"
Write-Host "  Remote:   $(if ($KeepRemote) { 'keep' } else { 'delete origin/' + $Branch })"
Write-Host ""

# --- Remove the worktree --------------------------------------------------
if ($WorktreePath) {
    $rmFlag = if ($Force) { " --force" } else { "" }
    Step "Removing worktree" "git worktree remove `"$WorktreePath`"$rmFlag"
} else {
    Write-Host "No worktree bound to '$Branch' (deleting branch only)." -ForegroundColor Yellow
}

# --- Delete local + remote branch -----------------------------------------
$delFlag = if ($Force) { "-D" } else { "-d" }
Step "Deleting local branch" "git branch $delFlag $Branch"

if (-not $KeepRemote) {
    Step "Deleting remote branch" "git push origin --delete $Branch"
}

# --- Prune stale refs -----------------------------------------------------
Step "Pruning worktrees" "git worktree prune"
Step "Pruning remote-tracking refs" "git fetch --prune"

Write-Host ""
if ($DryRun) {
    Write-Host "Dry run complete - nothing changed." -ForegroundColor Yellow
} else {
    Write-Host "close-worktree complete." -ForegroundColor Green
}
Write-Host ""
git worktree list
