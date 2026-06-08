# BAKLOG unified backup: personal data zip + internal docs to private repo.
#
# Usage (from repo root):
#   .\scripts\backup-all.ps1
#   .\scripts\backup-all.ps1 -SkipDataBackup
#   .\scripts\backup-all.ps1 -SkipInternalSync
#   .\scripts\backup-all.ps1 -InternalRepo "D:\repos\baklog-internal"
#
param(
    [string]$Destination = "",
    [int]$RetentionDays = 30,
    [switch]$IncludeBrowserProfiles,
    [string]$InternalRepo = "",
    [switch]$SkipDataBackup,
    [switch]$SkipInternalSync,
    [switch]$NoCommit
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$fullBackup = Join-Path $PSScriptRoot "full_backup.ps1"
$internalSync = Join-Path $PSScriptRoot "sync-internal-repo.ps1"

Write-Host ""
Write-Host "BAKLOG backup-all" -ForegroundColor Cyan
Write-Host "  Public repo:  $RepoRoot (code -> Ogrods/BAKLOG)"
Write-Host "  Internal:     marketing/docs/admin -> Ogrods/baklog-internal"
Write-Host "  Data zip:     games/cache/.env -> ..\baklog-backups (default)"
Write-Host ""

$dataOk = $true
$internalOk = $true

if (-not $SkipDataBackup) {
    Write-Host "--- Personal data backup ---" -ForegroundColor Cyan
    $dataParams = @{ RetentionDays = $RetentionDays }
    if ($Destination) { $dataParams.Destination = $Destination }
    if ($IncludeBrowserProfiles) { $dataParams.IncludeBrowserProfiles = $true }
    try {
        & $fullBackup @dataParams
        if ($LASTEXITCODE -ne 0) { throw "full_backup.ps1 exited with code $LASTEXITCODE" }
    } catch {
        $dataOk = $false
        Write-Host "Data backup failed: $_" -ForegroundColor Red
    }
} else {
    Write-Host "Skipping data backup (-SkipDataBackup)" -ForegroundColor Yellow
}

if (-not $SkipInternalSync) {
    Write-Host ""
    Write-Host "--- Internal docs sync (private repo) ---" -ForegroundColor Cyan
    $syncParams = @{ Push = $true }
    if ($InternalRepo) { $syncParams.InternalRepo = $InternalRepo }
    if ($NoCommit) { $syncParams.NoCommit = $true }
    try {
        & $internalSync @syncParams
        if ($LASTEXITCODE -ne 0) { throw "sync-internal-repo.ps1 exited with code $LASTEXITCODE" }
    } catch {
        $internalOk = $false
        Write-Host "Internal sync failed: $_" -ForegroundColor Red
    }
} else {
    Write-Host "Skipping internal sync (-SkipInternalSync)" -ForegroundColor Yellow
}

Write-Host ""
if ($dataOk -and $internalOk) {
    Write-Host "backup-all complete." -ForegroundColor Green
} else {
    Write-Host "backup-all finished with errors (see above)." -ForegroundColor Red
    exit 1
}
