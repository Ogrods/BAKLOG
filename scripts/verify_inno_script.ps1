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
    Write-Error "ISCC.exe not found. Install Inno Setup 6 or run on a Windows runner with choco install innosetup."
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

Write-Host "==> Installer branding assets"
& $Python (Join-Path $Root "packaging\generate_installer_assets.py")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

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
