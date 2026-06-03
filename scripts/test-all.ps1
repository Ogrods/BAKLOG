# Run Python and JavaScript test suites (same as CI).
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

Write-Host "==> pytest"
python -m pytest -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "==> vitest"
npm test
exit $LASTEXITCODE
