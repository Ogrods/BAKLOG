# Start BAKLOG with BAKLOG_ADMIN=1 and open the admin console.
# Usage:
#   .\scripts\start-admin.ps1
#   .\scripts\start-admin.ps1 -InstallShortcut   # (re)write Desktop "BAKLOG Admin.lnk"
#
# Desktop shortcut should be:
#   powershell.exe -NoExit -ExecutionPolicy Bypass -File "...\scripts\start-admin.ps1"

[CmdletBinding()]
param(
    [switch]$InstallShortcut
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Py = Join-Path $Root ".venv\Scripts\python.exe"
$AdminUrl = "http://127.0.0.1:8765/admin/"
$ShortcutName = "BAKLOG Admin.lnk"

function Write-AdminShortcut {
    $desktop = [Environment]::GetFolderPath("Desktop")
    $lnkPath = Join-Path $desktop $ShortcutName
    $scriptPath = Join-Path $PSScriptRoot "start-admin.ps1"
    $psExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    $shell = New-Object -ComObject WScript.Shell
    $lnk = $shell.CreateShortcut($lnkPath)
    $lnk.TargetPath = $psExe
    $lnk.Arguments = "-NoExit -ExecutionPolicy Bypass -File `"$scriptPath`""
    $lnk.WorkingDirectory = $Root
    $lnk.WindowStyle = 1
    $lnk.Description = "Start BAKLOG admin console (BAKLOG_ADMIN=1)"
    $lnk.Save()
    Write-Host "Wrote shortcut: $lnkPath"
}

function Test-AdminUp {
    try {
        $res = Invoke-WebRequest -Uri $AdminUrl -UseBasicParsing -TimeoutSec 2
        return ($res.StatusCode -ge 200 -and $res.StatusCode -lt 400)
    } catch {
        return $false
    }
}

function Open-AdminBrowser {
    Write-Host "Opening $AdminUrl"
    Start-Process $AdminUrl
}

if ($InstallShortcut) {
    Write-AdminShortcut
    exit 0
}

if (-not (Test-Path $Py)) {
    Write-Error "Missing $Py - run: py -3.13 -m venv .venv; .\.venv\Scripts\pip install -e '.[dev]'"
    exit 1
}

Set-Location $Root
$env:BAKLOG_ADMIN = "1"

if (Test-AdminUp) {
    Write-Host "Admin already responding at $AdminUrl - not starting a second server."
    Open-AdminBrowser
    exit 0
}

Write-Host "Starting BAKLOG with BAKLOG_ADMIN=1 ..."
Write-Host "Admin console: $AdminUrl"
Write-Host "(Close this window or Ctrl+C to stop the server.)"

# Open the browser once /admin/ answers (server boots in this process below).
$opener = Start-Job -ScriptBlock {
    param($Url)
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Milliseconds 500
        try {
            $res = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
            if ($res.StatusCode -ge 200 -and $res.StatusCode -lt 400) {
                Start-Process $Url
                return
            }
        } catch {
            # keep polling
        }
    }
} -ArgumentList $AdminUrl

try {
    & $Py server.py
} finally {
    Stop-Job $opener -ErrorAction SilentlyContinue
    Remove-Job $opener -Force -ErrorAction SilentlyContinue
}
