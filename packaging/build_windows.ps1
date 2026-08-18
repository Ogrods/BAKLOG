# Build BAKLOG Windows onedir bundle with PyInstaller + optional Inno Setup installer.
# Run from repo root. Requires: pip install pyinstaller, Node 22+ for frontend build.
# Optional: Inno Setup 6 (ISCC.exe) for BAKLOG-Setup.exe.
#
# Release artifacts use STABLE (un-versioned) filenames so the "latest" download
# URL never changes across releases:
#   https://github.com/Ogrods/BAKLOG/releases/latest/download/BAKLOG-win64.zip
#   https://github.com/Ogrods/BAKLOG/releases/latest/download/BAKLOG-Setup.exe
# The real version lives INSIDE the bundle (pyproject.toml + index.html meta).
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

Write-Host "Generating installer branding assets..."
& $Python (Join-Path $Root "packaging\generate_installer_assets.py")
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

$InternalDir = Join-Path $OutDir "_internal"
$FallbackJson = Join-Path $InternalDir "curated\free_claims.fallback.json"
if (-not (Test-Path $FallbackJson)) {
    Write-Error "Build failed: bundled curated feed missing at $FallbackJson (PyInstaller must ship curated/ for offline claims fallback)"
}

# pyproject.toml must be at bundle root for frozen version detection
Copy-Item -Force (Join-Path $Root "pyproject.toml") (Join-Path $OutDir "pyproject.toml")
Copy-Item -Force (Join-Path $Root "packaging\BETA-README.txt") (Join-Path $OutDir "BETA-README.txt")
Copy-Item -Force (Join-Path $Root "packaging\BAKLOG.ico") (Join-Path $OutDir "BAKLOG.ico")
Copy-Item -Force (Join-Path $Root "packaging\apply_update.ps1") (Join-Path $OutDir "apply_update.ps1")
Copy-Item -Force (Join-Path $Root "packaging\Uninstall BAKLOG.bat") (Join-Path $OutDir "Uninstall BAKLOG.bat")

Write-Host "Writing bundled account-auth .env..."
$urlSet = [bool]$env:BAKLOG_SUPABASE_URL
$anonSet = [bool]$env:BAKLOG_SUPABASE_ANON_KEY
Write-Host "  Auth env: BAKLOG_SUPABASE_URL=$(if ($urlSet) { 'set' } else { 'MISSING' }), BAKLOG_SUPABASE_ANON_KEY=$(if ($anonSet) { 'set' } else { 'MISSING' })"
& $Python (Join-Path $Root "scripts\write_bundle_auth_env.py") $OutDir
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# Full stop (not --dedupe): frozen smoke needs 8765 free. --dedupe keeps any
# live listener, which then fails frozen_bundle_smoke with port_collision.
Write-Host "Stopping stray BAKLOG servers on port 8765..."
& $Python scripts/stop_baklog.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Smoke: frozen bundle (migration + /api/config + fetcher dispatch)..."
& $Python scripts/frozen_bundle_smoke.py $OutDir
if ($LASTEXITCODE -ne 0) {
    Write-Error "frozen_bundle_smoke failed (exit $LASTEXITCODE)"
}
# Migration smoke moves co-located .env into %LOCALAPPDATA%\BAKLOG-Data; restore bundled auth for the zip.
Write-Host "Restoring bundled account-auth .env after migration smoke..."
& $Python (Join-Path $Root "scripts\write_bundle_auth_env.py") $OutDir
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

@"
@echo off
cd /d "%~dp0"
echo Starting BAKLOG (tray) on http://127.0.0.1:8765
echo Connections sign-in prefers Chrome or Edge. If neither is installed, BAKLOG downloads a one-time browser.
start "" "%~dp0BAKLOG Tray.exe"
"@ | Set-Content -Encoding ASCII (Join-Path $OutDir "Start BAKLOG.bat")

@"
@echo off
cd /d "%~dp0"
echo Starting BAKLOG server (console) on http://127.0.0.1:8765
echo Connections sign-in prefers Chrome or Edge. If neither is installed, BAKLOG downloads a one-time browser.
"%~dp0BAKLOG.exe"
pause
"@ | Set-Content -Encoding ASCII (Join-Path $OutDir "Start BAKLOG (server console).bat")

# Version label (from pyproject.toml) - embedded inside the bundle and passed to
# Inno Setup as the installer version. Release filenames stay STABLE (un-versioned)
# so the latest/download URL is permanent; the version is read from inside the zip.
$Version = "0.0.0"
$PyProject = Join-Path $Root "pyproject.toml"
if (Test-Path $PyProject) {
    if ((Get-Content $PyProject -Raw) -match 'version\s*=\s*"([^"]+)"') {
        $Version = $Matches[1]
    }
}

$ZipName = "BAKLOG-win64.zip"
$ZipPath = Join-Path $ReleaseDir $ZipName
if (Test-Path $ZipPath) { Remove-Item -Force $ZipPath }
Compress-Archive -Path $OutDir -DestinationPath $ZipPath -Force

$Hash = (Get-FileHash -Path $ZipPath -Algorithm SHA256).Hash.ToLower()
$HashFile = Join-Path $ReleaseDir "BAKLOG-win64.sha256"
"$Hash  $ZipName" | Set-Content -Encoding ASCII -NoNewline $HashFile

$SetupExe = Join-Path $ReleaseDir "BAKLOG-Setup.exe"
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
            if ($env:BAKLOG_REQUIRE_INSTALLER -eq "1") {
                Write-Error "Inno Setup compile failed (exit $LASTEXITCODE) and BAKLOG_REQUIRE_INSTALLER=1."
            }
            Write-Warning "Inno Setup compile failed (exit $LASTEXITCODE). Zip still available."
        }
    } finally {
        Pop-Location
    }
} else {
    if ($env:BAKLOG_REQUIRE_INSTALLER -eq "1") {
        Write-Error "ISCC.exe not found and BAKLOG_REQUIRE_INSTALLER=1."
    }
    Write-Warning "ISCC.exe not found - skipping BAKLOG-Setup.exe (install Inno Setup 6 to enable)."
}

if ($env:BAKLOG_REQUIRE_INSTALLER -eq "1" -and -not (Test-Path $SetupExe)) {
    Write-Error "BAKLOG-Setup.exe missing and BAKLOG_REQUIRE_INSTALLER=1."
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
    Write-Host "Copy the zip + .sha256 to testers. Library data defaults to %LOCALAPPDATA%\BAKLOG-Data (add portable.txt beside exe for co-located data)."
}
