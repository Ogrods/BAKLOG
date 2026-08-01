# Warn when the free-claims feed is older than MaxAgeDays (default 7).
# Reads landing/free-claims.json by default, or the live baklog.app URL with -Live.
#
# Usage (from repo root):
#   .\scripts\check_claims_feed_age.ps1
#   .\scripts\check_claims_feed_age.ps1 -Live
#   .\scripts\check_claims_feed_age.ps1 -MaxAgeDays 3

param(
    [switch]$Live,
    [int]$MaxAgeDays = 7,
    [string]$Path = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

if ($Live) {
    $url = "https://baklog.app/free-claims.json"
    Write-Host "Fetching $url ..."
    $doc = Invoke-RestMethod -Uri $url -Method Get
} else {
    if (-not $Path) {
        $Path = Join-Path $Root "landing\free-claims.json"
    }
    if (-not (Test-Path -LiteralPath $Path)) {
        Write-Host "WARN: missing feed file: $Path" -ForegroundColor Yellow
        exit 1
    }
    $doc = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

$generatedAt = [string]$doc.generated_at
if (-not $generatedAt) {
    Write-Host "WARN: feed has no generated_at" -ForegroundColor Yellow
    exit 1
}

try {
    $parsed = [datetimeoffset]::Parse($generatedAt, [System.Globalization.CultureInfo]::InvariantCulture)
} catch {
    Write-Host "WARN: could not parse generated_at=$generatedAt" -ForegroundColor Yellow
    exit 1
}

$age = [datetimeoffset]::UtcNow - $parsed.ToUniversalTime()
$ageDays = [math]::Round($age.TotalDays, 2)
Write-Host "generated_at=$generatedAt age=${ageDays}d (limit=${MaxAgeDays}d)"

if ($age.TotalDays -gt $MaxAgeDays) {
    Write-Host "WARN: free-claims feed is older than $MaxAgeDays days - refresh and republish." -ForegroundColor Yellow
    exit 1
}

Write-Host "OK: feed age within $MaxAgeDays days." -ForegroundColor Green
exit 0
