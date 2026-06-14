# Build BAKLOG Windows onedir bundle with PyInstaller + optional Inno Setup installer.
# Run from repo root. Requires: pip install pyinstaller, Node 22+ for frontend build.
# Optional: Inno Setup 6 (ISCC.exe) for BAKLOG-v*-Setup.exe.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File packaging/build_windows.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (Test-Path $VenvPython) {
    $Python = $VenvPython
} else {
    $Python = "python"
}

Write-Host "Installing Python dependencies..."
& $Python -m pip install -r requirements.txt
& $Python -m pip install pyinstaller

Write-Host "Building production frontend (esbuild dist/)..."
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Write-Error "npm not found - install Node.js 22+ before building the frozen bundle"
}
npm ci
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
npm run vendor:supabase
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
npm run build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
npm run check:dist-integrity
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$ReleaseDir = Join-Path $Root "release"
if (-not (Test-Path $ReleaseDir)) {
    New-Item -ItemType Directory -Path $ReleaseDir | Out-Null
}

Write-Host "Building BAKLOG.exe + BAKLOG Tray.exe (onedir)..."
& $Python -m PyInstaller packaging/baklog.spec --noconfirm --distpath $ReleaseDir

$OutDir = Join-Path $ReleaseDir "BAKLOG"
$ServerExe = Join-Path $OutDir "BAKLOG.exe"
$TrayExe = Join-Path $OutDir "BAKLOG Tray.exe"
if (-not (Test-Path $ServerExe)) {
    Write-Error "Build failed: $ServerExe not found"
}
if (-not (Test-Path $TrayExe)) {
    Write-Error "Build failed: $TrayExe not found"
}

Copy-Item -Force (Join-Path $Root "packaging\BETA-README.txt") (Join-Path $OutDir "BETA-README.txt")

@"
@echo off
cd /d "%~dp0"
echo Starting BAKLOG (tray) on http://127.0.0.1:8765
echo Connections sign-in requires Google Chrome or Microsoft Edge.
start "" "%~dp0BAKLOG Tray.exe"
"@ | Set-Content -Encoding ASCII (Join-Path $OutDir "Start BAKLOG.bat")

@"
@echo off
cd /d "%~dp0"
echo Starting BAKLOG server (console) on http://127.0.0.1:8765
echo Connections sign-in requires Google Chrome or Microsoft Edge.
"%~dp0BAKLOG.exe"
pause
"@ | Set-Content -Encoding ASCII (Join-Path $OutDir "Start BAKLOG (server console).bat")

# Version label for release artifacts (from pyproject.toml).
$Version = "0.0.0"
$PyProject = Join-Path $Root "pyproject.toml"
if (Test-Path $PyProject) {
    if ((Get-Content $PyProject -Raw) -match 'version\s*=\s*"([^"]+)"') {
        $Version = $Matches[1]
    }
}

$ZipName = "BAKLOG-v$Version-win64.zip"
$ZipPath = Join-Path $ReleaseDir $ZipName
if (Test-Path $ZipPath) { Remove-Item -Force $ZipPath }
Compress-Archive -Path $OutDir -DestinationPath $ZipPath -Force

$Hash = (Get-FileHash -Path $ZipPath -Algorithm SHA256).Hash.ToLower()
$HashFile = Join-Path $ReleaseDir "BAKLOG-v$Version-win64.sha256"
"$Hash  $ZipName" | Set-Content -Encoding ASCII -NoNewline $HashFile

$SetupExe = Join-Path $ReleaseDir "BAKLOG-v$Version-Setup.exe"
$Iscc = $null
if (Get-Command ISCC.exe -ErrorAction SilentlyContinue) {
    $Iscc = "ISCC.exe"
} else {
    $IsccCandidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    )
    foreach ($candidate in $IsccCandidates) {
        if (Test-Path $candidate) {
            $Iscc = $candidate
            break
        }
    }
}

if ($Iscc) {
    Write-Host "Building Inno Setup installer..."
    Push-Location (Join-Path $Root "packaging")
    try {
        & $Iscc "/DAppVersion=$Version" "baklog.iss"
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Inno Setup compile failed (exit $LASTEXITCODE). Zip still available."
        }
    } finally {
        Pop-Location
    }
} else {
    Write-Warning "ISCC.exe not found - skipping BAKLOG-v$Version-Setup.exe (install Inno Setup 6 to enable)."
}

Write-Host ""
Write-Host "Done."
Write-Host "  Folder:  $OutDir"
Write-Host "  Zip:     $ZipPath"
Write-Host "  SHA256:  $HashFile"
if (Test-Path $SetupExe) {
    Write-Host "  Setup:   $SetupExe"
    Write-Host "Ship the Setup.exe to beta testers (zip is the portable fallback)."
} else {
    Write-Host "Copy the zip + .sha256 to testers. Data files are written beside BAKLOG.exe."
}
