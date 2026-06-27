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

function Enter-NativeCommandScope {
    param([ValidateSet("Continue", "SilentlyContinue")][string]$Level = "Continue")
    $script:NativeScopePrevEap = $ErrorActionPreference
    $script:NativeScopePrevNative = $null
    $ErrorActionPreference = $Level
    if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -Scope Global -ErrorAction SilentlyContinue) {
        $script:NativeScopePrevNative = $PSNativeCommandUseErrorActionPreference
        $PSNativeCommandUseErrorActionPreference = $false
    }
}

function Exit-NativeCommandScope {
    $ErrorActionPreference = $script:NativeScopePrevEap
    if ($null -ne $script:NativeScopePrevNative) {
        $PSNativeCommandUseErrorActionPreference = $script:NativeScopePrevNative
    }
}

function Invoke-OptionalNative {
    param(
        [string]$Label,
        [scriptblock]$Command
    )
    Write-Host "- $Label"
    Enter-NativeCommandScope -Level SilentlyContinue
    try {
        try {
            & $Command 2>&1 | Out-Null
        } catch {}
        return $LASTEXITCODE
    } finally {
        Exit-NativeCommandScope
    }
}

function Invoke-RequiredNative {
    param(
        [string]$Label,
        [scriptblock]$Command
    )
    Write-Host "- $Label"
    Enter-NativeCommandScope
    try {
        try {
            & $Command
        } catch {}
        $code = $LASTEXITCODE
    } finally {
        Exit-NativeCommandScope
    }
    if ($code -ne 0) {
        throw "$Label failed (exit $code)."
    }
}

$pyVer = Read-PyProjectVersion
if ($pyVer -ne $bare) {
    throw "pyproject.toml version '$pyVer' does not match -Version '$bare'. Bump or fix version files first."
}

Write-Host "Replace release $tag from HEAD $(git rev-parse --short HEAD)"
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
}

Write-Host "Removing old release + tag (missing remote/local tag is ok):"
$releaseCode = Invoke-OptionalNative "GitHub release $tag" { gh release view $tag }
if ($releaseCode -eq 0) {
    Invoke-RequiredNative "Delete GitHub release $tag" { gh release delete $tag --yes }
} else {
    Write-Host "  release not found; skip delete"
}
$remoteCode = Invoke-OptionalNative "Remote tag $tag" { git push origin --delete $tag }
if ($remoteCode -ne 0) {
    Write-Host "  remote tag not found; skip delete"
}
$localCode = Invoke-OptionalNative "Local tag $tag" { git tag -d $tag }
if ($localCode -ne 0) {
    Write-Host "  local tag not found; skip delete"
}

Invoke-RequiredNative "Create tag $tag on HEAD" { git tag -a $tag -m "BAKLOG $tag (replacement build)" }
Invoke-RequiredNative "Push tag $tag" { git push origin $tag }

Write-Host "Done. Watch: gh run list --workflow=release.yml --limit 1"
