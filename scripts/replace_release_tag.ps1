# Replace a broken public release on the SAME version (pre-stranger beta policy).
# Deletes the remote tag + GitHub Release, re-tags HEAD, pushes tag to re-run release.yml.
# Usage (after fix is on main, version files match):
#   .\scripts\replace_release_tag.ps1 -Version 0.8.30
param(
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [switch]$DryRun,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$tag = if ($Version.StartsWith("v")) { $Version } else { "v$Version" }
$bare = $tag.TrimStart("v")

function Read-PyProjectVersion {
    $text = Get-Content -Raw (Join-Path $Root "pyproject.toml")
    if ($text -match 'version\s*=\s*"([^"]+)"') { return $Matches[1] }
    throw "Could not read version from pyproject.toml"
}

$pyVer = Read-PyProjectVersion
if ($pyVer -ne $bare) {
    throw "pyproject.toml version '$pyVer' does not match -Version '$bare'. Bump or fix version files first."
}

$branch = (git rev-parse --abbrev-ref HEAD).Trim()
if ($branch -ne "main") {
    throw "Refuse replace_release_tag: HEAD is '$branch' (must be on main)."
}
$status = git status --porcelain
if ($status) {
    throw "Refuse replace_release_tag: working tree is dirty. Commit or stash first."
}
git fetch origin main --quiet
$head = (git rev-parse HEAD).Trim()
$originMain = (git rev-parse origin/main).Trim()
if ($head -ne $originMain) {
    throw "Refuse replace_release_tag: HEAD ($head) is not origin/main ($originMain). Push/pull first."
}

Write-Host "Replace release $tag from HEAD $(git rev-parse --short HEAD) on main"
Write-Host "This deletes remote tag + GitHub Release, then re-pushes $tag (release.yml re-builds assets)."

if ($DryRun) {
    Write-Host "[DryRun] Would: gh release delete $tag; git push --delete origin $tag; git tag -a $tag; git push origin $tag"
    exit 0
}

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-Error "gh CLI required."
}

if (-not $Force) {
    $confirm = Read-Host "Type REPLACE $tag to continue"
    if ($confirm -ne "REPLACE $tag") {
        Write-Error "Aborted."
    }
} else {
    Write-Host "WARNING: -Force skips interactive confirm but still requires main + clean + origin/main tip."
}

$releaseExists = $false
try {
    gh release view $tag 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $releaseExists = $true }
} catch {
    $releaseExists = $false
}
if ($releaseExists) {
    gh release delete $tag --yes
}
git push origin --delete $tag 2>$null
if ($LASTEXITCODE -ne 0) { $global:LASTEXITCODE = 0 }
git tag -d $tag 2>$null
if ($LASTEXITCODE -ne 0) { $global:LASTEXITCODE = 0 }

git tag -a $tag -m "BAKLOG $tag (replacement build)"
git push origin $tag

Write-Host "Done. Watch: gh run list --workflow=release.yml --limit 1"
