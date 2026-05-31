# Build a distributable folder with Playwright Chromium bundled.
# Run from repo root after: pip install -r requirements.txt && playwright install chromium
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/build_installer.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

Write-Host "Installing Python dependencies..."
python -m pip install -r requirements.txt
python -m playwright install chromium

$Out = Join-Path $Root "dist\steam-backlog"
if (Test-Path $Out) { Remove-Item -Recurse -Force $Out }
New-Item -ItemType Directory -Path $Out | Out-Null

Write-Host "Copying application files..."
$Exclude = @('.git', '.venv', 'venv', 'node_modules', 'dist', '__pycache__', 'cache', 'data', '.env')
Get-ChildItem -Path $Root -Force | Where-Object {
    $Exclude -notcontains $_.Name
} | ForEach-Object {
    Copy-Item -Recurse -Force $_.FullName (Join-Path $Out $_.Name)
}

@"
@echo off
cd /d "%~dp0"
echo Starting Game Backlog server on http://127.0.0.1:8765
python server.py
pause
"@ | Set-Content -Encoding ASCII (Join-Path $Out "Start Backlog.bat")

Write-Host "Done. Output: $Out"
Write-Host "First run: open Connections tab and sign in to each store."
