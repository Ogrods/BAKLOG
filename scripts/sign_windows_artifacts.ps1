# Optional Authenticode signing for Windows release artifacts.
# Lead-time docs: baklog-internal/docs/CODE_SIGNING.md (private maintainer clone).
#
# Default: no-op (unsigned beta / local freeze). Set BAKLOG_SIGN_WINDOWS=1 and
# configure Azure Artifact Signing (or OV/EV) before this does real work.
#
# Usage (from repo root, after PyInstaller onedir exists):
#   powershell -File scripts/sign_windows_artifacts.ps1
#   powershell -File scripts/sign_windows_artifacts.ps1 -SetupOnly

param(
    [switch]$SetupOnly
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$ReleaseDir = Join-Path $Root "release"
$BundleDir = Join-Path $ReleaseDir "BAKLOG"
$SetupExe = Join-Path $ReleaseDir "BAKLOG-Setup.exe"

if ($env:BAKLOG_SIGN_WINDOWS -ne "1") {
    Write-Host "sign_windows_artifacts: skip (BAKLOG_SIGN_WINDOWS!=1). See docs/CODE_SIGNING.md in baklog-internal."
    exit 0
}

# Real signing is owner-gated until Azure Artifact Signing (or OV/EV) is wired.
# Fail closed when explicitly requested so CI does not publish "signed" lies.
$required = @(
    "AZURE_TENANT_ID",
    "AZURE_CLIENT_ID",
    "AZURE_SIGNING_ENDPOINT",
    "AZURE_SIGNING_ACCOUNT",
    "AZURE_SIGNING_PROFILE"
)
$missing = @($required | Where-Object { -not (Get-Item "env:$_" -ErrorAction SilentlyContinue).Value })
if ($missing.Count -gt 0) {
    Write-Error ("BAKLOG_SIGN_WINDOWS=1 but missing env: " + ($missing -join ", ") + ". Finish CODE_SIGNING.md checklist or unset BAKLOG_SIGN_WINDOWS.")
    exit 1
}

Write-Error @"
BAKLOG_SIGN_WINDOWS=1 is set and Azure env is present, but the SignTool / dotnet-sign
invocation is not wired yet. Complete identity validation + GHA OIDC per
baklog-internal/docs/CODE_SIGNING.md, then replace this stub with the real
sign commands (bundle exes before zip; Setup.exe after ISCC).
"@
exit 1
