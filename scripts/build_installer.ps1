# Build a distributable folder for BAKLOG.
# Run from repo root after: pip install -r requirements.txt
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

Write-Host "Copying application files..."
$Exclude = @('.git', '.venv', 'venv', 'node_modules', 'dist', '__pycache__', 'cache', 'data', '.env')
Get-ChildItem -Path $Root -Force | Where-Object {
    $Exclude -notcontains $_.Name
} | ForEach-Object {
    Copy-Item -Recurse -Force $_.FullName (Join-Path $Out $_.Name)
}

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
