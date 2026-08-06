# Run Python and JavaScript test suites (CI parity with optional -Full).
param(
    [switch]$Full
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

$VenvPy = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
if (Test-Path $VenvPy) {
    $Python = (Resolve-Path $VenvPy).Path
} else {
    $Python = "python"
}

# npm/Vitest may print deprecations on stderr; with $ErrorActionPreference=Stop,
# PowerShell treats NativeCommandError as terminating even when exit code is 0.
function Invoke-NpmStep {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Label,
        [Parameter(Mandatory = $true)]
        [string[]]$NpmArgs
    )
    Write-Host "==> $Label"
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & npm @NpmArgs
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prev
    }
    if ($code -ne 0) { exit $code }
}

Write-Host "==> ruff"
& $Python -m ruff check .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "==> pytest"
& $Python -m pytest --force-sugar -m "not integration and not slow and not release_smoke" --durations=20
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Invoke-NpmStep -Label "vitest" -NpmArgs @("test")
Invoke-NpmStep -Label "test:perf" -NpmArgs @("run", "test:perf")

if (-not $Full) {
    Write-Host ""
    Write-Host "Tip: .\scripts\test-all.ps1 -Full adds module-size, lint, build, and bundle checks (CI frontend-build job)."
    exit 0
}

Invoke-NpmStep -Label "check:module-size" -NpmArgs @("run", "check:module-size")
Invoke-NpmStep -Label "lint" -NpmArgs @("run", "lint")

Write-Host "==> vendor:supabase + build"
$prev = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    & npm run vendor:supabase
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & npm run build
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
    $ErrorActionPreference = $prev
}

Invoke-NpmStep -Label "check:bundle-size" -NpmArgs @("run", "check:bundle-size")
Invoke-NpmStep -Label "check:dist-integrity" -NpmArgs @("run", "check:dist-integrity")

Write-Host "==> audit free surface"
& $Python scripts/audit_free_surface_data.py --fail-on high --out .audit/report.json --baseline-out .audit/baseline.json --findings-out .audit/findings.yaml --handoff-out .audit/handoff.md --csv-out .audit/rows.csv
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "==> audit profile security"
& $Python scripts/audit_security.py --fail-on high --ignore-disk-bleed
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "==> release smoke (store API contracts; required before tagging)"
& $Python -m pytest -q -m release_smoke
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if ($IsWindows -or $env:OS -match "Windows") {
    Write-Host "==> verify_inno_script (ISCC compile; required before tagging on Windows)"
    $verifyInno = Join-Path $PSScriptRoot "verify_inno_script.ps1"
    if (Test-Path $verifyInno) {
        & powershell -ExecutionPolicy Bypass -File $verifyInno
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
}

# Frozen parity tests (requires BAKLOG.exe in release/)
$FrozenExe = Join-Path $PSScriptRoot "..\release\BAKLOG\BAKLOG.exe"
if (Test-Path $FrozenExe) {
    Write-Host "==> frozen_connect_smoke"
    & $Python (Join-Path $PSScriptRoot "frozen_connect_smoke.py") --exe $FrozenExe
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} else {
    Write-Host "==> frozen_connect_smoke (SKIPPED - no frozen exe at $FrozenExe)"
}

exit 0
