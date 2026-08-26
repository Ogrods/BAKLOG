# Compile packaging/baklog.iss against a minimal stub bundle (no PyInstaller).
# Catches ISCC syntax errors before tagging. Run on Windows with Inno Setup 6 installed.
param(
    [string]$AppVersion = "0.0.0-smoke"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Iscc = $null
if (Get-Command ISCC.exe -ErrorAction SilentlyContinue) {
    $Iscc = "ISCC.exe"
} else {
    foreach ($candidate in @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    )) {
        if (Test-Path $candidate) {
            $Iscc = $candidate
            break
        }
    }
}
if (-not $Iscc) {
    if ($env:BAKLOG_REQUIRE_INSTALLER -eq "1") {
        Write-Error "ISCC.exe not found and BAKLOG_REQUIRE_INSTALLER=1. Install Inno Setup 6 or run on a Windows runner with choco install innosetup."
    }
    Write-Warning "ISCC.exe not found - skipping Inno stub compile (install Inno Setup 6 for local Setup.exe smoke). CI python-windows still installs Inno and runs this gate."
    exit 0
}

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }

Write-Host "==> Stub release/BAKLOG for Inno [Files] section"
$StubRoot = Join-Path $Root "release\BAKLOG"
New-Item -ItemType Directory -Path $StubRoot -Force | Out-Null
foreach ($name in @("BAKLOG.exe", "BAKLOG Tray.exe", "apply_update.ps1", "BAKLOG.ico")) {
    $path = Join-Path $StubRoot $name
    if (-not (Test-Path $path)) {
        Set-Content -Path $path -Value "stub" -Encoding ASCII
    }
}

$assetFiles = @(
    (Join-Path $Root "packaging\BAKLOG.ico"),
    (Join-Path $Root "packaging\installer-icon.ico"),
    (Join-Path $Root "packaging\installer-wizard-large.bmp"),
    (Join-Path $Root "packaging\installer-wizard-small.bmp")
)
$missingAssets = @($assetFiles | Where-Object { -not (Test-Path $_) })
if ($missingAssets.Count -gt 0) {
    Write-Host "==> Installer branding assets (missing: $($missingAssets.Count))"
    & $Python -m pip install "Pillow>=10.0" -q
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $Python (Join-Path $Root "packaging\generate_installer_assets.py")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} else {
    Write-Host "==> Installer branding assets present (skip generate)"
}

Write-Host "==> ISCC compile packaging/baklog.iss"
Push-Location (Join-Path $Root "packaging")
try {
    & $Iscc "/DAppVersion=$AppVersion" "baklog.iss"
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Inno Setup compile failed (exit $LASTEXITCODE)."
    }
} finally {
    Pop-Location
}

$SetupExe = Join-Path $Root "release\BAKLOG-Setup.exe"
if (-not (Test-Path $SetupExe)) {
    Write-Error "Expected $SetupExe after ISCC compile."
}

Write-Host "Inno script OK: $SetupExe"
