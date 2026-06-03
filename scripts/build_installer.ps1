# Build a distributable folder for BAKLOG.
# Run from repo root after: pip install -r requirements.txt
# Connections sign-in requires Google Chrome or Microsoft Edge on the target machine.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/build_installer.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

Write-Host "Installing Python dependencies..."
python -m pip install -r requirements.txt

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

@"
@echo off
cd /d "%~dp0"
echo Starting BAKLOG server on http://127.0.0.1:8765
echo Connections sign-in requires Google Chrome or Microsoft Edge.
python server.py
pause
"@ | Set-Content -Encoding ASCII (Join-Path $Out "Start BAKLOG.bat")

Write-Host "Done. Output: $Out"
Write-Host "First run: open Connections tab and sign in to each store (Chrome or Edge required)."
