# README install smoke — fresh clone on a clean Windows machine (p3_readme_install).
#
# Follows README.md "Setup" + "Open the dashboard" Option A using only documented
# commands (venv + requirements.txt + server.py). Does not use the repo .venv.
#
# Usage (from any machine with git + Python 3.11+):
#   powershell -ExecutionPolicy Bypass -File scripts/readme_install_smoke.ps1
#
# Optional env:
#   README_SMOKE_PYTHON  — python launcher (default: py -3.13, then py -3, then python)
#   README_SMOKE_PORT      — listen port (default: 18765)
#   README_SMOKE_KEEP      — set 1 to leave the temp clone for inspection
#
# Exit 0 on pass; non-zero on first failure.

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Port = if ($env:README_SMOKE_PORT) { [int]$env:README_SMOKE_PORT } else { 18765 }
$Keep = $env:README_SMOKE_KEEP -eq "1"

function Resolve-PythonLauncher {
    if ($env:README_SMOKE_PYTHON) { return $env:README_SMOKE_PYTHON }
    foreach ($candidate in @("py -3.13", "py -3", "python")) {
        try {
            & cmd /c "$candidate -c `"import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)`""
            if ($LASTEXITCODE -eq 0) { return $candidate }
        } catch { }
    }
    throw "Python 3.11+ not found. Install Python or set README_SMOKE_PYTHON."
}

function Write-Step($msg) {
    Write-Host ""
    Write-Host "==> $msg" -ForegroundColor Cyan
}

$launcher = Resolve-PythonLauncher
$tempRoot = Join-Path $env:TEMP ("baklog-readme-smoke-" + [guid]::NewGuid().ToString("n").Substring(0, 8))
New-Item -ItemType Directory -Path $tempRoot | Out-Null
Write-Host "Temp clone: $tempRoot"

try {
    Write-Step "Export clean tree (git clone --local --depth 1)"
    Push-Location $RepoRoot
    git clone --local --depth 1 --branch (git rev-parse --abbrev-ref HEAD) $RepoRoot $tempRoot
    if ($LASTEXITCODE -ne 0) { throw "git clone failed" }
    Pop-Location
    Remove-Item -LiteralPath (Join-Path $tempRoot ".git") -Recurse -Force -ErrorAction SilentlyContinue

    Set-Location $tempRoot

    Write-Step "python -m venv .venv  (README Setup step 1)"
    & cmd /c "$launcher -m venv .venv"
    if ($LASTEXITCODE -ne 0) { throw "venv creation failed" }
    $Py = Join-Path $tempRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path $Py)) { throw "missing $Py after venv" }

    Write-Step "pip install -r requirements.txt  (README Setup step 1)"
    & $Py -m pip install --upgrade pip
    & $Py -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

    Write-Step "python server.py  (README Open the dashboard)"
    $env:BAKLOG_PROFILE = "readme-smoke"
    $env:PORT = "$Port"
    $server = Start-Process -FilePath $Py -ArgumentList "server.py" -PassThru -WindowStyle Hidden
    $deadline = (Get-Date).AddSeconds(45)
    $ready = $false
    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/config" -UseBasicParsing -TimeoutSec 3
            if ($resp.StatusCode -eq 200) {
                $ready = $true
                break
            }
        } catch { Start-Sleep -Milliseconds 500 }
    }
    if (-not $ready) { throw "server did not respond on port $Port within 45s" }

    Write-Step "GET / and /api/config"
    $index = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/" -UseBasicParsing -TimeoutSec 10
    if ($index.StatusCode -ne 200) { throw "GET / returned $($index.StatusCode)" }
    if ($index.Content -notmatch "BAKLOG") { throw "GET / body missing BAKLOG marker" }

    $cfg = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/config" -UseBasicParsing -TimeoutSec 10
    $json = $cfg.Content | ConvertFrom-Json
    if ($json.frozen -ne $false) { throw "expected frozen=false for source install" }

    Write-Host ""
    Write-Host "PASS: README install smoke completed on port $Port" -ForegroundColor Green
    Write-Host "Python: $launcher"
    Write-Host "Clone:  $tempRoot"
}
finally {
    try {
        if ($server -and -not $server.HasExited) {
            Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
        }
    } catch { }
    if (-not $Keep) {
        Set-Location $env:TEMP
        if (Test-Path $tempRoot) {
            Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    } else {
        Write-Host "README_SMOKE_KEEP=1 - left clone at $tempRoot" -ForegroundColor Yellow
    }
}
