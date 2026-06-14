# Build a distributable folder for BAKLOG (portable .venv copy).
# Prefer packaging/build_windows.ps1 (PyInstaller BAKLOG.exe + BAKLOG Tray.exe) for beta testers.
# Connections sign-in requires Google Chrome or Microsoft Edge on the target machine.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/build_installer.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$VenvPythonw = Join-Path $Root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Error "Missing $VenvPython — create the venv first: python -m venv .venv"
}
if (-not (Test-Path $VenvPythonw)) {
    Write-Warning "Missing $VenvPythonw — tray launcher will use python.exe (console may flash)."
    $VenvPythonw = $VenvPython
}

Write-Host "Installing Python dependencies (dev venv)..."
& $VenvPython -m pip install -r requirements.txt
& $VenvPython -m pip install pystray Pillow

Write-Host "Verifying tray dependencies..."
& $VenvPython -c "import pystray; from PIL import Image"
if ($LASTEXITCODE -ne 0) {
    Write-Error "pystray/Pillow failed to import after install."
}

$Out = Join-Path $Root "dist\baklog"
if (Test-Path $Out) { Remove-Item -Recurse -Force $Out }
New-Item -ItemType Directory -Path $Out | Out-Null

# Copy from git archive when possible (tracked files only — no profiles/, games_*.json, etc.).
$ArchiveZip = Join-Path $env:TEMP "baklog-portable-src.zip"
$UsedGitArchive = $false
if (Get-Command git -ErrorAction SilentlyContinue) {
    Push-Location $Root
    try {
        & git archive HEAD -o $ArchiveZip 2>$null
        if ($LASTEXITCODE -eq 0 -and (Test-Path $ArchiveZip)) {
            Expand-Archive -Path $ArchiveZip -DestinationPath $Out -Force
            $UsedGitArchive = $true
            Write-Host "Copied tracked files via git archive (personal data excluded by .gitignore)."
        }
    } finally {
        Pop-Location
        if (Test-Path $ArchiveZip) { Remove-Item -Force $ArchiveZip }
    }
}

if (-not $UsedGitArchive) {
    Write-Warning "git archive unavailable — falling back to denylist copy (verify output before shipping)."
    $Exclude = @(
        '.git', '.venv', 'venv', 'node_modules', 'dist', '__pycache__', 'cache', 'data', '.env',
        'profiles', 'admin', 'docs', 'marketing', 'audit', 'landing', 'tracker.html',
        'IP.md', 'EVENT_AUDIT.md', 'EVENT_AUDIT.json', 'review-handoff.md', 'FREE_SURFACE_REVIEW.md',
        '.env.imported', 'itad_prices.json', 'free_claims.json', 'refresh.log', '.cursor',
        'build', 'lighthouse', '.pytest_cache', '.ruff_cache', 'steam_backlog.egg-info'
    )
    Get-ChildItem -Path $Root -Force | Where-Object {
        $name = $_.Name
        if ($Exclude -contains $name) { return $false }
        if ($name -like 'games_*.json') { return $false }
        if ($name -like 'games_wishlist_*.json') { return $false }
        if ($name -like 'debug-*.log') { return $false }
        if ($name -like '.cursor*') { return $false }
        return $true
    } | ForEach-Object {
        Copy-Item -Recurse -Force $_.FullName (Join-Path $Out $_.Name)
    }
}

function Assert-NoShipLeaks {
    param([string]$Dir)
    $leaks = @()
    Get-ChildItem -Path $Dir -Recurse -Force -ErrorAction SilentlyContinue | ForEach-Object {
        $rel = $_.FullName.Substring($Dir.Length).TrimStart('\', '/')
        if ($_.Name -eq 'secrets.bin') { $leaks += "secrets.bin at $rel" }
        if ($rel -match '\\cache\\auth\\profiles\\' -or $rel -match '/cache/auth/profiles/') {
            $leaks += "CDP session profile at $rel"
        }
        if ($_.Name -like 'games_*.json' -and $rel -notmatch '\\tests\\' -and $rel -notmatch '/tests/') {
            $leaks += "library JSON at $rel"
        }
        if ($_.Name -eq 'tracker.html') { $leaks += "internal tracker.html at $rel" }
    }
    if ($leaks.Count -gt 0) {
        Write-Error ("Build output contains data that must not ship to testers:`n" + ($leaks -join "`n"))
    }
}

Write-Host "Verifying output contains no credentials or personal catalog data..."
Assert-NoShipLeaks -Dir $Out

Write-Host "Creating portable venv in output..."
$OutPython = Join-Path $Out ".venv\Scripts\python.exe"
$OutPythonw = Join-Path $Out ".venv\Scripts\pythonw.exe"
& $VenvPython -m venv (Join-Path $Out ".venv")
& $OutPython -m pip install -r (Join-Path $Out "requirements.txt")
& $OutPython -m pip install pystray Pillow
& $OutPython -c "import pystray; from PIL import Image"
if ($LASTEXITCODE -ne 0) {
    Write-Error "Output venv: pystray/Pillow failed to import."
}
if (-not (Test-Path $OutPythonw)) {
    $OutPythonw = $OutPython
}

@"
@echo off
cd /d "%~dp0"
echo Starting BAKLOG server on http://127.0.0.1:8765
echo Connections sign-in requires Google Chrome or Microsoft Edge.
"%~dp0.venv\Scripts\python.exe" server.py
pause
"@ | Set-Content -Encoding ASCII (Join-Path $Out "Start BAKLOG.bat")

@"
@echo off
cd /d "%~dp0"
rem Launch BAKLOG into the system tray (opens your backlog in a browser window).
start "" "%~dp0.venv\Scripts\pythonw.exe" tray_app.py
"@ | Set-Content -Encoding ASCII (Join-Path $Out "Start BAKLOG (tray).bat")

Write-Host "Done. Output: $Out"
Write-Host "First run: open Connections tab and sign in to each store (Chrome or Edge required)."
Write-Host "Tray launcher: 'Start BAKLOG (tray).bat' (bundled .venv includes pystray + Pillow)."
