# Run Python and JavaScript test suites (CI parity with optional -Full).
param(
    [switch]$Full
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

Write-Host "==> pytest"
python -m pytest -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "==> vitest"
npm test
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (-not $Full) {
    Write-Host ""
    Write-Host "Tip: .\scripts\test-all.ps1 -Full adds module-size, lint, build, and bundle checks (CI frontend-build job)."
    exit 0
}

Write-Host "==> check:module-size"
npm run check:module-size
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "==> lint"
npm run lint
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "==> vendor:supabase + build"
npm run vendor:supabase
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
npm run build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "==> check:bundle-size"
npm run check:bundle-size
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "==> check:dist-integrity"
npm run check:dist-integrity
exit $LASTEXITCODE
