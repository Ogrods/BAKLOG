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
#   .\scripts\close-worktree.ps1 feat/ads-polish -SkipBackup   # skip backup tag/bundle
#
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Branch,
    [switch]$KeepRemote,
    [switch]$Force,
    [switch]$DryRun,
    [switch]$SkipBackup
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

if ($Branch -notmatch '^(feat|fix|chore)/[a-z0-9][a-z0-9._-]*$') {
    Write-Host "Rejected branch name: '$Branch'" -ForegroundColor Red
    Write-Host "Use one concern per branch with a prefix: feat/ , fix/ , or chore/" -ForegroundColor Yellow
    exit 1
}

function Invoke-GitStep {
    param(
        [string]$Desc,
        [string[]]$Args
    )
    $cmd = "git $($Args -join ' ')"
    if ($DryRun) {
        Write-Host "[dry-run] $Desc" -ForegroundColor Yellow
        Write-Host "          $cmd" -ForegroundColor DarkGray
        return
    }
    Write-Host "--- $Desc ---" -ForegroundColor Cyan
    & git @Args
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Args[0]) failed (exit $LASTEXITCODE): $Desc"
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

if (-not $DryRun -and -not $SkipBackup) {
    $tag = "backup/$($Branch -replace '/','-')-$(Get-Date -Format 'yyyy-MM-dd')"
    Invoke-GitStep "Tagging backup $tag" @("tag", $tag, $Branch)
}

# --- Remove the worktree --------------------------------------------------
if ($WorktreePath) {
    $rmArgs = @("worktree", "remove", $WorktreePath)
    if ($Force) { $rmArgs += "--force" }
    Invoke-GitStep "Removing worktree" $rmArgs
} else {
    Write-Host "No worktree bound to '$Branch' (deleting branch only)." -ForegroundColor Yellow
}

# --- Delete local + remote branch -----------------------------------------
$delArgs = @("branch")
if ($Force) { $delArgs += "-D" } else { $delArgs += "-d" }
$delArgs += $Branch
Invoke-GitStep "Deleting local branch" $delArgs

if (-not $KeepRemote) {
    Invoke-GitStep "Deleting remote branch" @("push", "origin", "--delete", $Branch)
}

# --- Prune stale refs -----------------------------------------------------
Invoke-GitStep "Pruning worktrees" @("worktree", "prune")
Invoke-GitStep "Pruning remote-tracking refs" @("fetch", "--prune")

Write-Host ""
if ($DryRun) {
    Write-Host "Dry run complete - nothing changed." -ForegroundColor Yellow
} else {
    Write-Host "close-worktree complete." -ForegroundColor Green
}
Write-Host ""
git worktree list
