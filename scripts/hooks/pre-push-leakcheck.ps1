# Fail the push if tracked files match sensitive patterns (audit 2026-06-09).
$ErrorActionPreference = "Stop"
$repoRoot = git rev-parse --show-toplevel 2>$null
if (-not $repoRoot) { exit 0 }

$patterns = @(
    "games_*.json",
    "games_wishlist_*.json",
    "itad_prices.json",
    "free_claims.json",
    "profiles/",
    "data/",
    ".env",
    "secrets.bin",
    "tracker.html",
    "cache/auth/"
)

$tracked = git -C $repoRoot ls-files 2>$null
if (-not $tracked) { exit 0 }

$hits = @()
foreach ($line in $tracked) {
    $norm = $line -replace '\\', '/'
    foreach ($pat in $patterns) {
        if ($pat.EndsWith('/')) {
            if ($norm -like "$pat*") { $hits += $line; break }
        } elseif ($pat.Contains('*')) {
            if ($norm -like $pat) { $hits += $line; break }
        } else {
            if ($norm -eq $pat -or $norm -like "*/$pat") { $hits += $line; break }
        }
    }
}

if ($hits.Count -gt 0) {
    Write-Host "[pre-push] BLOCKED: sensitive paths are tracked in git:" -ForegroundColor Red
    $hits | ForEach-Object { Write-Host "  $_" }
    Write-Host "Remove from the index (git rm --cached) before pushing to the public remote." -ForegroundColor Red
    exit 1
}
exit 0
