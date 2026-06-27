# Apply a verified BAKLOG release zip over an existing install (Windows).
# Invoked by the local server after security checks — not for manual arbitrary use.
param(
    [Parameter(Mandatory = $true)]
    [string]$ManifestPath
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Error $Message
    exit 1
}

function Test-SafeChildPath([string]$Root, [string]$Relative) {
    $rootFull = [System.IO.Path]::GetFullPath($Root)
    $targetFull = [System.IO.Path]::GetFullPath((Join-Path $Root $Relative))
    return $targetFull.StartsWith($rootFull, [System.StringComparison]::OrdinalIgnoreCase)
}

function Get-FileSha256([string]$Path) {
    $hash = Get-FileHash -Path $Path -Algorithm SHA256
    return $hash.Hash.ToLowerInvariant()
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

$updateRoot = [System.IO.Path]::GetFullPath((Join-Path $env:TEMP "BAKLOG-update"))
$zipFull = [System.IO.Path]::GetFullPath($zipPath)
if (-not $zipFull.StartsWith($updateRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
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

Wait-ProcessGone -ProcessId $serverPid -TimeoutSec 45
Wait-ProcessGone -ProcessId $trayPid -TimeoutSec 15

$staging = Join-Path $updateRoot ("staging-" + [Guid]::NewGuid().ToString("n"))
New-Item -ItemType Directory -Path $staging | Out-Null

try {
    Expand-Archive -LiteralPath $zipPath -DestinationPath $staging -Force

    $bundleRoot = $null
    Get-ChildItem -Path $staging -Recurse -Filter "BAKLOG.exe" -File | ForEach-Object {
        $parent = $_.Directory.FullName
        $trayExe = Join-Path $parent "BAKLOG Tray.exe"
        if (Test-Path -LiteralPath $trayExe) {
            $script:bundleRoot = $parent
        }
    }
    if (-not $bundleRoot) {
        Fail "Extracted bundle layout invalid"
    }

    $backupDir = Join-Path ([System.IO.Path]::GetDirectoryName($installDir)) ("BAKLOG-backup-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
    Copy-Item -LiteralPath $installDir -Destination $backupDir -Recurse -Force

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

    $trayExePath = Join-Path $installDir "BAKLOG Tray.exe"
    if (-not (Test-Path -LiteralPath $trayExePath)) {
        Fail "Updated bundle missing tray launcher"
    }

    Start-Process -FilePath $trayExePath -WorkingDirectory $installDir | Out-Null
} finally {
    if (Test-Path -LiteralPath $staging) {
        Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue
    }
}

exit 0
