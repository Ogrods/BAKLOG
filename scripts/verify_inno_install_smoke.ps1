# Silent-install smoke for BAKLOG-Setup.exe (post-build gate).
param(
    [string]$SetupExe = "",
    [string]$InstallDir = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

if (-not $SetupExe) {
    $SetupExe = Join-Path $Root "release\BAKLOG-Setup.exe"
}
if (-not (Test-Path $SetupExe)) {
    Write-Error "Setup not found: $SetupExe"
}

if (-not $InstallDir) {
    $InstallDir = Join-Path $env:RUNNER_TEMP "baklog-inno-smoke"
    if (-not $env:RUNNER_TEMP) {
        $InstallDir = Join-Path $env:TEMP "baklog-inno-smoke"
    }
}

if (Test-Path $InstallDir) {
    Remove-Item -LiteralPath $InstallDir -Recurse -Force
}
New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null

$LogPath = Join-Path (Split-Path $InstallDir -Parent) "baklog-inno-smoke.log"
Write-Host "==> Silent install smoke -> $InstallDir"
$proc = Start-Process -FilePath $SetupExe -ArgumentList @(
    "/VERYSILENT",
    "/SUPPRESSMSGBOXES",
    "/NORESTART",
    "/DIR=$InstallDir",
    "/LOG=$LogPath"
) -Wait -PassThru
if ($proc.ExitCode -ne 0) {
    if (Test-Path $LogPath) { Get-Content $LogPath -Tail 40 }
    Write-Error "Setup exited $($proc.ExitCode). Log: $LogPath"
}

$TrayExe = Join-Path $InstallDir "BAKLOG Tray.exe"
$ServerExe = Join-Path $InstallDir "BAKLOG.exe"
foreach ($required in @($TrayExe, $ServerExe)) {
    if (-not (Test-Path $required)) {
        Write-Error "Missing after install: $required"
    }
}

Write-Host "Inno silent install smoke OK"
