# Authenticode helpers for Windows release artifacts.
#
# Signing itself runs in .github/workflows/release.yml via
# azure/artifact-signing-action (Azure Artifact Signing, OIDC). This script only
# lists what to sign and verifies the result, so it works the same locally and
# in CI. Local packaging/build_windows.ps1 builds stay unsigned.
#
# Usage (from repo root):
#   # Write absolute paths of .exe files that still need a signature
#   powershell -File scripts/sign_windows_artifacts.ps1 -List -Root release\BAKLOG -OutFile files.txt
#   powershell -File scripts/sign_windows_artifacts.ps1 -List -Path release\BAKLOG-Setup.exe
#
#   # Require a Valid, timestamped signature on every .exe (non-zero exit otherwise)
#   powershell -File scripts/sign_windows_artifacts.ps1 -Verify -Root release\BAKLOG
#   powershell -File scripts/sign_windows_artifacts.ps1 -Verify -Path release\BAKLOG-Setup.exe -ExpectedSubject "CN=..."
#
# -ExpectedSubject is a substring match on the signer subject. It applies to the
# executables we build (top level of -Root, plus -Path), not to third-party
# executables nested deeper in the bundle, which keep their vendor signatures.

param(
    [switch]$List,
    [switch]$Verify,
    [string]$Root = "",
    [string]$Path = "",
    [string]$OutFile = "",
    [string]$ExpectedSubject = ""
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "sign_windows_artifacts: $Message" -ForegroundColor Red
    exit 1
}

if ($List -eq $Verify) {
    Fail "pass exactly one of -List or -Verify."
}
if (-not $Root -and -not $Path) {
    Fail "pass -Root <bundle dir> and/or -Path <file.exe>."
}

# Each entry: @{ File = <FileInfo>; Own = <bool> } where Own means "we built it".
$targets = New-Object System.Collections.Generic.List[object]

if ($Root) {
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
        Fail "root folder not found: $Root"
    }
    $rootFull = (Resolve-Path -LiteralPath $Root).Path.TrimEnd('\')
    $exes = @(Get-ChildItem -LiteralPath $rootFull -Recurse -File -Filter "*.exe" | Sort-Object FullName)
    if ($exes.Count -eq 0) {
        Fail "no .exe files under $rootFull"
    }
    foreach ($exe in $exes) {
        $own = ($exe.DirectoryName.TrimEnd('\') -ieq $rootFull)
        $targets.Add(@{ File = $exe; Own = $own })
    }
}

if ($Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        Fail "file not found: $Path"
    }
    $targets.Add(@{ File = (Get-Item -LiteralPath $Path); Own = $true })
}

if ($List) {
    $toSign = New-Object System.Collections.Generic.List[string]
    foreach ($t in $targets) {
        $sig = Get-AuthenticodeSignature -LiteralPath $t.File.FullName
        if ($sig.Status -eq "Valid" -and -not $t.Own) {
            Write-Host "skip (already signed by $($sig.SignerCertificate.Subject)): $($t.File.FullName)"
            continue
        }
        $toSign.Add($t.File.FullName)
    }
    if ($toSign.Count -eq 0) {
        Fail "nothing to sign."
    }
    foreach ($f in $toSign) { Write-Host "to sign: $f" }
    if ($OutFile) {
        $parent = Split-Path -Parent $OutFile
        if ($parent -and -not (Test-Path -LiteralPath $parent)) {
            New-Item -ItemType Directory -Path $parent -Force | Out-Null
        }
        [System.IO.File]::WriteAllLines($OutFile, [string[]]$toSign.ToArray())
        Write-Host "Wrote $($toSign.Count) path(s) to $OutFile"
    } else {
        $toSign | Write-Output
    }
    exit 0
}

$failures = 0
foreach ($t in $targets) {
    $file = $t.File.FullName
    $sig = Get-AuthenticodeSignature -LiteralPath $file
    $subject = if ($sig.SignerCertificate) { $sig.SignerCertificate.Subject } else { "(none)" }
    $stamper = if ($sig.TimeStamperCertificate) { $sig.TimeStamperCertificate.Subject } else { "" }

    $problems = @()
    if ($sig.Status -ne "Valid") {
        $problems += "status $($sig.Status): $($sig.StatusMessage)"
    }
    if ($sig.Status -eq "Valid" -and -not $stamper) {
        $problems += "signature has no RFC 3161 timestamp"
    }
    if ($ExpectedSubject -and $t.Own -and $subject.IndexOf($ExpectedSubject, [System.StringComparison]::OrdinalIgnoreCase) -lt 0) {
        $problems += "signer subject does not contain '$ExpectedSubject'"
    }

    if ($problems.Count -gt 0) {
        $failures++
        Write-Host "FAIL  $file" -ForegroundColor Red
        foreach ($p in $problems) { Write-Host "      $p" -ForegroundColor Red }
    } else {
        Write-Host "OK    $file"
    }
    Write-Host "      signer:      $subject"
    Write-Host "      timestamper: $(if ($stamper) { $stamper } else { '(none)' })"
}

if ($failures -gt 0) {
    Fail "$failures file(s) unsigned or invalid."
}
Write-Host "sign_windows_artifacts: all $($targets.Count) file(s) have valid, timestamped signatures."
exit 0
