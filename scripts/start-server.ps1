# Start the BAKLOG dev server with the project venv (avoids Windows Store python.exe stub).
$Root = Split-Path -Parent $PSScriptRoot
$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) {
    Write-Error "Missing $Py - run: py -3.13 -m venv .venv; .\.venv\Scripts\pip install -e '.[dev]'"
    exit 1
}
Set-Location $Root
& $Py server.py @args
