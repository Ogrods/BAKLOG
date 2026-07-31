# Apply a verified BAKLOG release zip over an existing install (Windows).
# Invoked by the local server after security checks — not for manual arbitrary use.
param(
    [Parameter(Mandatory = $true)]
    [string]$ManifestPath
)

$ErrorActionPreference = "Stop"

$script:UpdateRoot = [System.IO.Path]::GetFullPath((Join-Path $env:TEMP "BAKLOG-update"))
New-Item -ItemType Directory -Path $script:UpdateRoot -Force | Out-Null

function Fail([string]$Message) {
    Write-ApplyResult -Ok $false -ErrorMessage $Message -Restored $false
    Write-Error $Message
    exit 1
}

function Write-ApplyResult {
    param(
        [bool]$Ok,
        [string]$ErrorMessage = "",
        [string]$Version = "",
        [bool]$Restored = $false
    )
    $resultPath = Join-Path $script:UpdateRoot "apply-result.json"
    $payload = @{
        ok = $Ok
        error = $ErrorMessage
        version = $Version
        restored_from_backup = $Restored
        finished_at = (Get-Date).ToUniversalTime().ToString("o")
    }
    $payload | ConvertTo-Json | Set-Content -LiteralPath $resultPath -Encoding UTF8
    # Allow the tray watchdog to resume auto-restart after apply finishes.
    Remove-Item -LiteralPath (Join-Path $script:UpdateRoot "applying.lock") -Force -ErrorAction SilentlyContinue
}

function Test-SafeChildPath([string]$Root, [string]$Relative) {
    $rootFull = [System.IO.Path]::GetFullPath($Root)
    $targetFull = [System.IO.Path]::GetFullPath((Join-Path $Root $Relative))
    return $targetFull.StartsWith($rootFull, [System.StringComparison]::OrdinalIgnoreCase)
}

function Get-FileSha256([string]$Path) {
    # Prefer .NET so -NoProfile / minimal runners still work (Get-FileHash may be absent).
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $stream = [System.IO.File]::OpenRead($Path)
        try {
            $hashBytes = $sha.ComputeHash($stream)
            return ([System.BitConverter]::ToString($hashBytes) -replace "-", "").ToLowerInvariant()
        } finally {
            $stream.Dispose()
        }
    } finally {
        $sha.Dispose()
    }
}

function Restore-InstallFromBackup([string]$InstallDir, [string]$BackupDir) {
    if (-not (Test-Path -LiteralPath $BackupDir)) { return $false }
    Get-ChildItem -LiteralPath $InstallDir -Force | ForEach-Object {
        Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
    }
    Copy-Item -LiteralPath (Join-Path $BackupDir "*") -Destination $InstallDir -Recurse -Force
    return $true
}

function Remove-OldBackups([string]$InstallParent, [string]$KeepBackup) {
    Get-ChildItem -LiteralPath $InstallParent -Directory -Filter "BAKLOG-backup-*" |
        Where-Object { $_.FullName -ne $KeepBackup } |
        ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue }
}

if (-not (Test-Path -LiteralPath $ManifestPath)) {
    Fail "Manifest not found"
}

try {
    $manifest = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
} catch {
    Fail "Manifest JSON invalid"
}

$installDir = [string]$manifest.install_dir
$zipPath = [string]$manifest.zip_path
$expectedSha = ([string]$manifest.sha256).ToLowerInvariant()
$version = [string]$manifest.version
$serverPid = [int]$manifest.server_pid
$trayPid = [int]$manifest.tray_pid

if (-not $installDir -or -not (Test-Path -LiteralPath $installDir)) {
    Fail "Install dir missing"
}
if (-not (Test-Path -LiteralPath (Join-Path $installDir "BAKLOG.exe"))) {
    Fail "Install dir is not a BAKLOG bundle"
}
if (-not $zipPath -or -not (Test-Path -LiteralPath $zipPath)) {
    Fail "Update zip missing"
}
if ($expectedSha -notmatch '^[0-9a-f]{64}$') {
    Fail "Expected sha256 invalid"
}

$actualSha = Get-FileSha256 $zipPath
if ($actualSha -ne $expectedSha) {
    Fail "Update zip sha256 mismatch"
}

$zipFull = [System.IO.Path]::GetFullPath($zipPath)
if (-not $zipFull.StartsWith($script:UpdateRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    Fail "Zip path outside trusted update workspace"
}

function Wait-ProcessGone([int]$ProcessId, [int]$TimeoutSec) {
    if ($ProcessId -le 0) { return }
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (-not (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)) { return }
        Start-Sleep -Milliseconds 250
    }
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

function Kill-ProcessTree([int]$ProcessId) {
    if ($ProcessId -le 0) { return }
    # Tree-kill the process and all its children (fetchers, browser windows, etc.)
    taskkill /F /T /PID $ProcessId 2>&1 | Out-Null
}

# Apply is launched detached from BAKLOG.exe. Stop the tray tree first (it owns
# the server); waiting alone used to leave the tray watchdog free to respawn
# BAKLOG.exe and lock install files during copy.
Kill-ProcessTree -ProcessId $trayPid
Kill-ProcessTree -ProcessId $serverPid
Wait-ProcessGone -ProcessId $serverPid -TimeoutSec 45
Wait-ProcessGone -ProcessId $trayPid -TimeoutSec 15
Kill-ProcessTree -ProcessId $trayPid
Kill-ProcessTree -ProcessId $serverPid

$staging = Join-Path $script:UpdateRoot ("staging-" + [Guid]::NewGuid().ToString("n"))
New-Item -ItemType Directory -Path $staging | Out-Null
$backupDir = $null

try {
    Expand-Archive -LiteralPath $zipPath -DestinationPath $staging -Force

    $bundleRoot = $null
    $bundleExe = Get-ChildItem -Path $staging -Recurse -Filter "BAKLOG.exe" -File |
        Where-Object {
            Test-Path -LiteralPath (Join-Path $_.Directory.FullName "BAKLOG Tray.exe")
        } |
        Select-Object -First 1
    if ($bundleExe) {
        $bundleRoot = $bundleExe.Directory.FullName
    }
    if (-not $bundleRoot) {
        Fail "Extracted bundle layout invalid"
    }

    $installParent = [System.IO.Path]::GetDirectoryName($installDir)
    $backupDir = Join-Path $installParent ("BAKLOG-backup-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
    Copy-Item -LiteralPath $installDir -Destination $backupDir -Recurse -Force

    try {
        Get-ChildItem -LiteralPath $bundleRoot -Force | ForEach-Object {
            $dest = Join-Path $installDir $_.Name
            if ($_.PSIsContainer) {
                if (Test-Path -LiteralPath $dest) {
                    Remove-Item -LiteralPath $dest -Recurse -Force
                }
                Copy-Item -LiteralPath $_.FullName -Destination $dest -Recurse -Force
            } else {
                Copy-Item -LiteralPath $_.FullName -Destination $dest -Force
            }
        }
    } catch {
        $restored = Restore-InstallFromBackup -InstallDir $installDir -BackupDir $backupDir
        Write-ApplyResult -Ok $false -ErrorMessage $_.Exception.Message -Version $version -Restored $restored
        exit 1
    }

    $trayExePath = Join-Path $installDir "BAKLOG Tray.exe"
    if (-not (Test-Path -LiteralPath $trayExePath)) {
        $restored = Restore-InstallFromBackup -InstallDir $installDir -BackupDir $backupDir
        Write-ApplyResult -Ok $false -ErrorMessage "Updated bundle missing tray launcher" -Version $version -Restored $restored
        exit 1
    }

    Remove-OldBackups -InstallParent $installParent -KeepBackup $backupDir
    Write-ApplyResult -Ok $true -Version $version -Restored $false
    # Drop ready package so the relaunched app does not rehydrate Install & restart.
    $versionDir = Join-Path $script:UpdateRoot $version
    if (Test-Path -LiteralPath $versionDir) {
        Remove-Item -LiteralPath (Join-Path $versionDir "ready.json") -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath (Join-Path $versionDir "package.zip") -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath (Join-Path $versionDir "apply-manifest.json") -Force -ErrorAction SilentlyContinue
        try { Remove-Item -LiteralPath $versionDir -Force -ErrorAction SilentlyContinue } catch {}
    }
    Start-Process -FilePath $trayExePath -WorkingDirectory $installDir | Out-Null
} finally {
    if (Test-Path -LiteralPath $staging) {
        Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue
    }
}

exit 0
