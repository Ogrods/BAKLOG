# Pre-tag release gate - run locally before: git tag -a vX.Y.Z && git push origin vX.Y.Z
# Mirrors release.yml checks plus CI frontend-build budgets so PyInstaller is not wasted.
param(
    [string]$TagVersion = "",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (Test-Path $VenvPython) {
    $Python = $VenvPython
    $env:PATH = "$(Split-Path $VenvPython);$env:PATH"
} else {
    $Python = "python"
}

function Read-PyProjectVersion {
    $text = Get-Content -Raw (Join-Path $Root "pyproject.toml")
    if ($text -match 'version\s*=\s*"([^"]+)"') { return $Matches[1] }
    throw "Could not read version from pyproject.toml"
}

function Read-PackageJsonVersion {
    $pkg = Get-Content -Raw (Join-Path $Root "package.json") | ConvertFrom-Json
    return [string]$pkg.version
}

function Read-IndexHtmlVersion {
    $html = Get-Content -Raw (Join-Path $Root "index.html")
    if ($html -match 'name="baklog-version"\s+content="([^"]+)"') { return $Matches[1] }
    throw 'Could not read baklog-version from index.html'
}

Write-Host "==> Version sync (pyproject.toml, package.json, index.html)"
$pyVer = Read-PyProjectVersion
$pkgVer = Read-PackageJsonVersion
$htmlVer = Read-IndexHtmlVersion
if ($pyVer -ne $pkgVer -or $pyVer -ne $htmlVer) {
    throw "Version mismatch: pyproject=$pyVer package.json=$pkgVer index.html=$htmlVer"
}
Write-Host "    $pyVer (all three match)"

if ($TagVersion) {
    $tag = $TagVersion.TrimStart("v")
    if ($tag -ne $pyVer) {
        throw "Tag version '$tag' does not match pyproject version '$pyVer'"
    }
    Write-Host "    Tag v$tag matches pyproject"
}

Write-Host "==> GitHub Actions secrets (repository)"
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-Warning "gh CLI not found - skip secret check (verify BAKLOG_SUPABASE_URL + ANON_KEY in repo Settings)"
} else {
    $secrets = @(gh secret list --json name -q '.[].name' 2>$null)
    foreach ($required in @("BAKLOG_SUPABASE_URL", "BAKLOG_SUPABASE_ANON_KEY")) {
        if ($secrets -notcontains $required) {
            throw "Missing GitHub repository secret: $required (Settings -> Secrets -> Actions)"
        }
    }
    Write-Host "    BAKLOG_SUPABASE_URL + BAKLOG_SUPABASE_ANON_KEY present"
    if ($secrets -contains "BAKLOG_SUPABASE_JWT_SECRET") {
        Write-Host "    BAKLOG_SUPABASE_JWT_SECRET present in GitHub (dev/HS256 only - never bundled into release zips)"
    }
}

Write-Host "==> CI parity (test-all -Full)"
& (Join-Path $Root "scripts\test-all.ps1") -Full
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if ($IsWindows -and (Test-Path (Join-Path $Root "scripts\verify_inno_script.ps1"))) {
    Write-Host "==> verify_inno_script (ISCC compile against stub bundle)"
    powershell -ExecutionPolicy Bypass -File (Join-Path $Root "scripts\verify_inno_script.ps1") -AppVersion $pyVer
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} elseif (-not $IsWindows) {
    Write-Warning "Skipping verify_inno_script (Windows + Inno Setup 6 only). CI python-windows job must be green before tagging."
}

if ($SkipBuild) {
    Write-Host ""
    Write-Host "Preflight OK (build skipped). Next: packaging/build_windows.ps1, then tag + push tag."
    exit 0
}

Write-Host "==> Local auth env for bundled .env"
$hasUrl = [bool]$env:BAKLOG_SUPABASE_URL
$hasAnon = [bool]$env:BAKLOG_SUPABASE_ANON_KEY
if (-not $hasUrl -or -not $hasAnon) {
    $bundleAuth = Join-Path $Root "packaging\bundle-auth.env"
    $dotEnv = Join-Path $Root ".env"
    if ((Test-Path $bundleAuth) -or (Test-Path $dotEnv)) {
        Write-Host "    Will read from packaging/bundle-auth.env or repo .env during build"
    } else {
        throw "No BAKLOG_SUPABASE_URL/ANON_KEY in env and no packaging/bundle-auth.env or .env - frozen build will fail write_bundle_auth_env"
    }
} else {
    Write-Host "    Process env has URL + ANON_KEY"
}

Write-Host "==> packaging/build_windows.ps1"
powershell -ExecutionPolicy Bypass -File (Join-Path $Root "packaging\build_windows.ps1")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$BundleDir = Join-Path $Root "release\BAKLOG"
Write-Host ""
Write-Host "Preflight OK for v$pyVer. Manual smoke checklist (before tagging):"
Write-Host "  1. Launch: $BundleDir\BAKLOG Tray.exe"
Write-Host "  2. Confirm version badge shows v$pyVer"
Write-Host "  3. Sign-in gate loads (Supabase auth)"
Write-Host "  4. One Connect flow if this release touched store auth"
Write-Host ""
Write-Host "When manual smoke passes and main is clean with CI green:"
Write-Host "  git tag -a v$pyVer -m ""BAKLOG v$pyVer"""
Write-Host "  git push origin v$pyVer"
Write-Host ""
Write-Host "Tag push rebuilds on GitHub Actions; do not upload the local zip/Setup."
