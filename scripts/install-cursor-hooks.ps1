# Copy project Cursor hooks into .cursor/hooks.json (session-end tracker reminder + stray dedupe).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$src = Join-Path $root "scripts\hooks\cursor-hooks.project.json"
$dest = Join-Path $root ".cursor\hooks.json"
if (-not (Test-Path $src)) {
    Write-Error "Missing template: $src"
}
New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null
Copy-Item -Force $src $dest
Write-Host "Installed $dest"
Write-Host "Restart Cursor or reload hooks if the session-end reminder still does not appear."
