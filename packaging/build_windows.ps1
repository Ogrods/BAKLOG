# Build BAKLOG Windows onedir bundle with PyInstaller.
# Run from repo root. Requires: pip install pyinstaller, Node 22+ for frontend build.
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
    Write-Error "npm not found — install Node.js 22+ before building the frozen bundle"
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

Write-Host "Building BAKLOG.exe (onedir)..."
& $Python -m PyInstaller packaging/baklog.spec --noconfirm --distpath $ReleaseDir

$OutDir = Join-Path $ReleaseDir "BAKLOG"
$Exe = Join-Path $OutDir "BAKLOG.exe"
if (-not (Test-Path $Exe)) {
    Write-Error "Build failed: $Exe not found"
}

Copy-Item -Force (Join-Path $Root "packaging\BETA-README.txt") (Join-Path $OutDir "BETA-README.txt")

@"
@echo off
cd /d "%~dp0"
echo Starting BAKLOG on http://127.0.0.1:8765
echo Connections sign-in requires Google Chrome or Microsoft Edge.
start "" "%~dp0BAKLOG.exe"
"@ | Set-Content -Encoding ASCII (Join-Path $OutDir "Start BAKLOG.bat")

# Version label for the zip filename (from pyproject.toml).
$Version = "0.0.0"
$PyProject = Join-Path $Root "pyproject.toml"
if (Test-Path $PyProject) {
    if ($PyProject -match 'version\s*=\s*"([^"]+)"') {
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

Write-Host ""
Write-Host "Done."
Write-Host "  Folder: $OutDir"
Write-Host "  Zip:    $ZipPath"
Write-Host "  SHA256: $HashFile"
Write-Host "Copy the zip + .sha256 to testers. Data files are written beside BAKLOG.exe."
