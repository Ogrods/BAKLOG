# Build BAKLOG Windows onedir bundle with PyInstaller.
# Run from repo root. Requires: pip install pyinstaller
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File packaging/build_windows.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

Write-Host "Installing dependencies..."
python -m pip install -r requirements.txt
python -m pip install pyinstaller

Write-Host "Building BAKLOG.exe (onedir)..."
python -m PyInstaller packaging/baklog.spec --noconfirm

Write-Host "Done. Output: dist\BAKLOG\BAKLOG.exe"
Write-Host "Copy dist\BAKLOG\ to testers. Data files are written beside BAKLOG.exe."
