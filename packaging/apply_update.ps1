# Apply a verified BAKLOG release zip over an existing install (Windows).
# Invoked by the local server after security checks — not for manual arbitrary use.
param(
    [Parameter(Mandatory = $true)]
    [string]$ManifestPath
)

$ErrorActionPreference = "Stop"

$script:UpdateRoot = [System.IO.Path]::GetFullPath((Join-Path $env:TEMP "BAKLOG-update"))
New-Item -ItemType Directory -Path $script:UpdateRoot -Force | Out-Null
$script:ApplyLog = Join-Path $script:UpdateRoot "apply.log"
$script:KilledApps = $false
$script:InstallDir = $null
$script:BackupDir = $null
$script:CopyStarted = $false
$script:ResultWritten = $false
$script:Version = ""

function Write-ApplyLog([string]$Message) {
    $ts = (Get-Date).ToUniversalTime().ToString("o")
    $line = "[$ts] $Message"
    try {
        Add-Content -LiteralPath $script:ApplyLog -Value $line -Encoding UTF8 -ErrorAction SilentlyContinue
    } catch {}
    Write-Host $line
}

function Write-ApplyStarted {
    $path = Join-Path $script:UpdateRoot "apply-started.json"
    $payload = @{
        pid = $PID
        written_at = (Get-Date).ToUniversalTime().ToString("o")
        version = $script:Version
    }
    $payload | ConvertTo-Json | Set-Content -LiteralPath $path -Encoding UTF8
}

function Clear-ApplyStarted {
    Remove-Item -LiteralPath (Join-Path $script:UpdateRoot "apply-started.json") -Force -ErrorAction SilentlyContinue
}

function Touch-ApplyingLock {
    $path = Join-Path $script:UpdateRoot "applying.lock"
    if (Test-Path -LiteralPath $path) {
        (Get-Item -LiteralPath $path).LastWriteTimeUtc = [DateTime]::UtcNow
    } else {
        @{
            version = $script:Version
            written_at = (Get-Date).ToUniversalTime().ToString("o")
        } | ConvertTo-Json | Set-Content -LiteralPath $path -Encoding UTF8
    }
}

function Write-ApplyResult {
    param(
        [bool]$Ok,
        [string]$ErrorMessage = "",
        [string]$Version = "",
        [bool]$Restored = $false
    )
    if ($script:ResultWritten) { return }
    $script:ResultWritten = $true
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
    Clear-ApplyStarted
    Write-ApplyLog ("result ok=$Ok version=$Version error=$ErrorMessage restored=$Restored")
}

function Test-SafeChildPath([string]$Root, [string]$Relative) {
    $rootFull = [System.IO.Path]::GetFullPath($Root)
    $targetFull = [System.IO.Path]::GetFullPath((Join-Path $Root $Relative))
    return $targetFull.StartsWith($rootFull, [System.StringComparison]::OrdinalIgnoreCase)
}

function Get-FileSha256([string]$Path) {
    # Prefer .NET so -NoProfile / minimal runners still work (Microsoft.PowerShell.Utility hash cmdlets may be absent).
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

function Expand-ZipDotNet([string]$ZipPath, [string]$Destination) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    if (Test-Path -LiteralPath $Destination) {
        [System.IO.Directory]::CreateDirectory($Destination) | Out-Null
    }
    [System.IO.Compression.ZipFile]::ExtractToDirectory($ZipPath, $Destination)
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

function Get-AncestorPidSet([int]$StartPid) {
    $set = @{}
    $set[$StartPid] = $true
    $current = $StartPid
    for ($i = 0; $i -lt 32; $i++) {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$current" -ErrorAction SilentlyContinue
        if (-not $proc) { break }
        $parent = [int]$proc.ParentProcessId
        if ($parent -le 0 -or $set.ContainsKey($parent)) { break }
        $set[$parent] = $true
        $current = $parent
    }
    return $set
}

function Get-DescendantPids([int]$RootPid, $ExcludeSet) {
    $out = New-Object System.Collections.Generic.List[int]
    $queue = New-Object System.Collections.Generic.Queue[int]
    $seen = @{}
    $queue.Enqueue($RootPid)
    $seen[$RootPid] = $true
    while ($queue.Count -gt 0) {
        $currentPid = $queue.Dequeue()
        if (-not $ExcludeSet.ContainsKey($currentPid)) {
            $out.Add($currentPid) | Out-Null
        }
        $children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$currentPid" -ErrorAction SilentlyContinue
        foreach ($child in $children) {
            $cid = [int]$child.ProcessId
            if ($seen.ContainsKey($cid)) { continue }
            $seen[$cid] = $true
            if ($ExcludeSet.ContainsKey($cid)) { continue }
            $queue.Enqueue($cid)
        }
    }
    return $out
}

function Stop-ProcessTreeExcludingSelf([int]$RootPid) {
    if ($RootPid -le 0) { return }
    $exclude = Get-AncestorPidSet -StartPid $PID
    $exclude[$PID] = $true
    $targets = Get-DescendantPids -RootPid $RootPid -ExcludeSet $exclude
    # Kill leaves first (reverse of BFS discovery order is approximate; force each).
    for ($i = $targets.Count - 1; $i -ge 0; $i--) {
        $tid = $targets[$i]
        if ($tid -eq $PID) { continue }
        if ($exclude.ContainsKey($tid)) { continue }
        Stop-Process -Id $tid -Force -ErrorAction SilentlyContinue
    }
}

function Wait-ProcessGone([int]$ProcessId, [int]$TimeoutSec) {
    if ($ProcessId -le 0) { return }
    if ($ProcessId -eq $PID) { return }
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (-not (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)) { return }
        Start-Sleep -Milliseconds 250
    }
    if ($ProcessId -ne $PID) {
        Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
    }
}

function Start-TrayIfPresent {
    if (-not $script:InstallDir) { return }
    $trayExePath = Join-Path $script:InstallDir "BAKLOG Tray.exe"
    if (Test-Path -LiteralPath $trayExePath) {
        Write-ApplyLog "relaunching tray: $trayExePath"
        Start-Process -FilePath $trayExePath -WorkingDirectory $script:InstallDir | Out-Null
    } else {
        Write-ApplyLog "tray exe missing; cannot relaunch"
    }
}

# --- main ---
Write-ApplyLog "apply_update.ps1 start pid=$PID manifest=$ManifestPath"
Write-ApplyStarted
Touch-ApplyingLock

try {
    if (-not (Test-Path -LiteralPath $ManifestPath)) {
        throw "Manifest not found"
    }

    try {
        $manifest = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        throw "Manifest JSON invalid"
    }

    $installDir = [string]$manifest.install_dir
    $zipPath = [string]$manifest.zip_path
    $expectedSha = ([string]$manifest.sha256).ToLowerInvariant()
    $script:Version = [string]$manifest.version
    $serverPid = [int]$manifest.server_pid
    $trayPid = [int]$manifest.tray_pid
    $script:InstallDir = $installDir

    Write-ApplyStarted
    Touch-ApplyingLock
    Write-ApplyLog "validate install=$installDir version=$($script:Version) trayPid=$trayPid serverPid=$serverPid"

    if (-not $installDir -or -not (Test-Path -LiteralPath $installDir)) {
        throw "Install dir missing"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $installDir "BAKLOG.exe"))) {
        throw "Install dir is not a BAKLOG bundle"
    }
    if (-not $zipPath -or -not (Test-Path -LiteralPath $zipPath)) {
        throw "Update zip missing"
    }
    if ($expectedSha -notmatch '^[0-9a-f]{64}$') {
        throw "Expected sha256 invalid"
    }

    $actualSha = Get-FileSha256 $zipPath
    if ($actualSha -ne $expectedSha) {
        throw "Update zip sha256 mismatch"
    }

    $zipFull = [System.IO.Path]::GetFullPath($zipPath)
    if (-not $zipFull.StartsWith($script:UpdateRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Zip path outside trusted update workspace"
    }

    # Apply helper is a descendant of tray→server. Never tree-kill via the OS
    # task-kill utility — it would kill this script. Walk Win32_Process and skip
    # our own PID/ancestors.
    Write-ApplyLog "killing tray/server trees (excluding apply pid=$PID)"
    Stop-ProcessTreeExcludingSelf -RootPid $trayPid
    Stop-ProcessTreeExcludingSelf -RootPid $serverPid
    $script:KilledApps = $true
    Wait-ProcessGone -ProcessId $serverPid -TimeoutSec 45
    Wait-ProcessGone -ProcessId $trayPid -TimeoutSec 15
    Stop-ProcessTreeExcludingSelf -RootPid $trayPid
    Stop-ProcessTreeExcludingSelf -RootPid $serverPid
    Touch-ApplyingLock
    Write-ApplyLog "kill phase complete"

    $staging = Join-Path $script:UpdateRoot ("staging-" + [Guid]::NewGuid().ToString("n"))
    New-Item -ItemType Directory -Path $staging | Out-Null
    try {
        Write-ApplyLog "extracting zip to $staging"
        Expand-ZipDotNet -ZipPath $zipPath -Destination $staging
        Touch-ApplyingLock

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
            throw "Extracted bundle layout invalid"
        }

        $installParent = [System.IO.Path]::GetDirectoryName($installDir)
        $script:BackupDir = Join-Path $installParent ("BAKLOG-backup-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
        Write-ApplyLog "backup to $($script:BackupDir)"
        Copy-Item -LiteralPath $installDir -Destination $script:BackupDir -Recurse -Force
        Touch-ApplyingLock

        try {
            $script:CopyStarted = $true
            Write-ApplyLog "copying bundle overlay"
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
            $restored = Restore-InstallFromBackup -InstallDir $installDir -BackupDir $script:BackupDir
            Write-ApplyResult -Ok $false -ErrorMessage $_.Exception.Message -Version $script:Version -Restored $restored
            Start-TrayIfPresent
            exit 1
        }

        $trayExePath = Join-Path $installDir "BAKLOG Tray.exe"
        if (-not (Test-Path -LiteralPath $trayExePath)) {
            $restored = Restore-InstallFromBackup -InstallDir $installDir -BackupDir $script:BackupDir
            Write-ApplyResult -Ok $false -ErrorMessage "Updated bundle missing tray launcher" -Version $script:Version -Restored $restored
            Start-TrayIfPresent
            exit 1
        }

        Remove-OldBackups -InstallParent $installParent -KeepBackup $script:BackupDir
        Write-ApplyResult -Ok $true -Version $script:Version -Restored $false
        # Drop ready package so the relaunched app does not rehydrate Install & restart.
        $versionDir = Join-Path $script:UpdateRoot $script:Version
        if (Test-Path -LiteralPath $versionDir) {
            Remove-Item -LiteralPath (Join-Path $versionDir "ready.json") -Force -ErrorAction SilentlyContinue
            Remove-Item -LiteralPath (Join-Path $versionDir "package.zip") -Force -ErrorAction SilentlyContinue
            Remove-Item -LiteralPath (Join-Path $versionDir "apply-manifest.json") -Force -ErrorAction SilentlyContinue
            try { Remove-Item -LiteralPath $versionDir -Force -ErrorAction SilentlyContinue } catch {}
        }
        Write-ApplyLog "starting tray"
        Start-Process -FilePath $trayExePath -WorkingDirectory $installDir | Out-Null
    } finally {
        if (Test-Path -LiteralPath $staging) {
            Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
} catch {
    $msg = $_.Exception.Message
    if (-not $msg) { $msg = "$_" }
    Write-ApplyLog "FATAL: $msg"
    $restored = $false
    if ($script:CopyStarted -and $script:BackupDir -and $script:InstallDir) {
        $restored = Restore-InstallFromBackup -InstallDir $script:InstallDir -BackupDir $script:BackupDir
    }
    Write-ApplyResult -Ok $false -ErrorMessage $msg -Version $script:Version -Restored $restored
    if ($script:KilledApps) {
        Start-TrayIfPresent
    }
    exit 1
}

exit 0
