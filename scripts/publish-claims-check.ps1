# Pre-deploy maintainer check for the free-claims feed.
# fetch -> dry-run build -> audit -> optional Vercel deploy hook.
#
# Usage (from repo root):
#   .\scripts\publish-claims-check.ps1
#   $env:BAKLOG_VERCEL_DEPLOY_HOOK = "https://api.vercel.com/v1/integrations/deploy/..."
#   .\scripts\publish-claims-check.ps1 -SkipFetch

param(
    [switch]$SkipFetch,
    [switch]$SkipDeploy
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Missing venv Python at $Python — run from repo root with .venv installed."
}

function Invoke-Step {
    param([string]$Label, [scriptblock]$Action)
    Write-Host ""
    Write-Host "==> $Label" -ForegroundColor Cyan
    & $Action
    if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) {
        throw "$Label failed (exit $LASTEXITCODE)"
    }
}

if (-not $SkipFetch) {
    Invoke-Step "fetch_claim_sources.py" {
        & $Python fetch_claim_sources.py
    }
}

Invoke-Step "build_free_claims.py --dry-run" {
    & $Python build_free_claims.py --dry-run --no-profile
}

Invoke-Step "audit_free_surface_data.py --fail-on high" {
    & $Python scripts\audit_free_surface_data.py --fail-on high
}

if ($SkipDeploy) {
    Write-Host ""
    Write-Host "SkipDeploy set — not triggering Vercel." -ForegroundColor Yellow
    exit 0
}

$hook = $env:BAKLOG_VERCEL_DEPLOY_HOOK
if ($hook) {
    Invoke-Step "POST BAKLOG_VERCEL_DEPLOY_HOOK" {
        Invoke-RestMethod -Method Post -Uri $hook | Out-Null
        Write-Host "Deploy hook triggered." -ForegroundColor Green
    }
} else {
    Write-Host ""
    Write-Host "Checks passed. Next: publish for real, commit landing/, deploy to Vercel." -ForegroundColor Green
    Write-Host "  .\.venv\Scripts\python.exe build_free_claims.py"
    Write-Host "  git add landing/free-claims.json curated/free_claims.fallback.json"
    Write-Host "  git commit && git push   # or set BAKLOG_VERCEL_DEPLOY_HOOK and re-run this script"
}
