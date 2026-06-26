# Run Python and JavaScript test suites (CI parity with optional -Full).
param(
    [switch]$Full
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

Write-Host "==> ruff"
python -m ruff check .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "==> pytest"
python -m pytest --force-sugar -m "not integration and not slow and not release_smoke" --durations=20
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "==> vitest"
npm test
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "==> test:perf"
npm run test:perf
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
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "==> audit free surface"
python scripts/audit_free_surface_data.py --fail-on high --out .audit/report.json --baseline-out .audit/baseline.json --findings-out .audit/findings.yaml --handoff-out .audit/handoff.md --csv-out .audit/rows.csv
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "==> audit profile security"
python scripts/audit_security.py --fail-on high --ignore-disk-bleed
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "==> release smoke (store API contracts; required before tagging)"
python -m pytest -q -m release_smoke
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

exit 0
