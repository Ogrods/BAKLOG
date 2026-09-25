"""Guards for Windows Authenticode signing in release.yml (Azure Artifact Signing)."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
SIGN_SCRIPT = ROOT / "scripts" / "sign_windows_artifacts.ps1"
BUILD_SCRIPT = ROOT / "packaging" / "build_windows.ps1"

SIGN_ACTION = "azure/artifact-signing-action@v2"


def _windows_job() -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index("\n  build:\n")
    end = text.index("\n  build-macos:\n")
    return text[start:end]


def _job_header(job: str) -> str:
    return job.split("\n    steps:\n", 1)[0]


def _steps(job: str) -> list[str]:
    body = job.split("\n    steps:\n", 1)[1]
    return [s for s in re.split(r"\n(?=      - )", body) if s.strip().startswith("- ")]


def _index(steps: list[str], needle: str) -> int:
    hits = [i for i, s in enumerate(steps) if needle in s]
    assert hits, f"no step containing {needle!r}"
    return hits[0]


def _all_indexes(steps: list[str], needle: str) -> list[int]:
    return [i for i, s in enumerate(steps) if needle in s]


def test_windows_job_uses_release_environment_and_oidc() -> None:
    header = _job_header(_windows_job())
    assert re.search(r"^    environment: release$", header, re.M)
    assert re.search(r"^      id-token: write", header, re.M)
    assert re.search(r"^      contents: write", header, re.M)


def test_other_os_jobs_do_not_use_release_environment() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    other = text[text.index("\n  build-macos:\n") :]
    assert "environment: release" not in other
    assert SIGN_ACTION not in other


def test_signing_steps_gated_on_signing_enabled() -> None:
    job = _windows_job()
    assert "SIGNING_ENABLED: ${{ vars.SIGNING_ENABLED }}" in _job_header(job)
    steps = _steps(job)
    gated_markers = ("azure/login@", SIGN_ACTION, "sign_windows_artifacts.ps1")
    gated = [s for s in steps if any(m in s for m in gated_markers)]
    assert len(gated) >= 7
    for step in gated:
        assert "if: env.SIGNING_ENABLED == 'true'" in step, step.splitlines()[0]


def test_unsigned_path_warns_and_enabled_without_endpoint_fails() -> None:
    steps = _steps(_windows_job())
    check = steps[_index(steps, "Check code signing config")]
    assert "if:" not in check.split("run:", 1)[0]
    assert "::warning" in check and "UNSIGNED" in check
    assert "::error" in check and "AZURE_SIGNING_ENDPOINT" in check
    assert _index(steps, "Check code signing config") < _index(steps, "Run Python tests")


def test_bundle_signed_before_installer_and_installer_signed_before_upload() -> None:
    steps = _steps(_windows_job())
    bundle = _index(steps, "build_windows.ps1 -Stage Bundle")
    package = _index(steps, "build_windows.ps1 -Stage Package")
    sign_idx = _all_indexes(steps, SIGN_ACTION)
    assert len(sign_idx) == 2
    sign_bundle, sign_setup = sign_idx
    verify_bundle = _index(steps, 'Verify = $true; Root = "release/BAKLOG"')
    verify_setup = _index(steps, 'Verify = $true; Path = "release/BAKLOG-Setup.exe"')
    install_smoke = _index(steps, "verify_inno_install_smoke.ps1")
    attest = _index(steps, "attest-build-provenance")
    publish = _index(steps, "gh release")

    assert "steps.bundle_files.outputs.files" in steps[sign_bundle]
    assert "BAKLOG-Setup.exe" in steps[sign_setup]
    assert bundle < sign_bundle < verify_bundle < package < sign_setup < verify_setup
    assert verify_setup < install_smoke < attest < publish

    logins = _all_indexes(steps, "azure/login@v3")
    assert len(logins) == 2
    assert logins[0] < sign_bundle and package < logins[1] < sign_setup


def test_sign_action_inputs() -> None:
    steps = _steps(_windows_job())
    for i in _all_indexes(steps, SIGN_ACTION):
        step = steps[i]
        assert "endpoint: ${{ vars.AZURE_SIGNING_ENDPOINT }}" in step
        assert "vars.AZURE_SIGNING_ACCOUNT || 'baklog-signing'" in step
        assert "vars.AZURE_SIGNING_PROFILE || 'baklog-release'" in step
        assert "file-digest: SHA256" in step
        assert "timestamp-rfc3161: http://timestamp.acs.microsoft.com" in step
        assert "timestamp-digest: SHA256" in step
        assert "exclude-azure-cli-credential: false" in step
        for cred in (
            "environment",
            "workload-identity",
            "managed-identity",
            "shared-token-cache",
            "visual-studio",
            "visual-studio-code",
            "azure-powershell",
            "azure-developer-cli",
            "interactive-browser",
        ):
            assert f"exclude-{cred}-credential: true" in step, cred


def test_no_hardcoded_signing_endpoint() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "codesigning.azure.net" not in text
    assert "secrets.AZURE_CLIENT_ID" in text


def test_build_script_stages_and_no_signing_stub() -> None:
    text = BUILD_SCRIPT.read_text(encoding="utf-8")
    assert '[ValidateSet("All", "Bundle", "Package")]' in text
    assert "BAKLOG_SIGN_WINDOWS" not in text
    assert 'sign_windows_artifacts.ps1")' not in text
    assert text.index("PyInstaller packaging/baklog.spec") < text.index("Compress-Archive")
    assert text.index("Compress-Archive") < text.index('"baklog.iss"')


def test_sign_script_exists_with_modes() -> None:
    assert SIGN_SCRIPT.is_file()
    text = SIGN_SCRIPT.read_text(encoding="utf-8")
    for token in ("[switch]$List", "[switch]$Verify", "$ExpectedSubject", "Get-AuthenticodeSignature"):
        assert token in text


def _powershell() -> str | None:
    return shutil.which("powershell") or shutil.which("pwsh")


@pytest.mark.skipif(sys.platform != "win32", reason="Authenticode helpers are Windows-only")
def test_sign_script_list_and_verify_smoke(tmp_path: Path) -> None:
    ps = _powershell()
    if not ps:
        pytest.skip("PowerShell not available")
    bundle = tmp_path / "BAKLOG"
    (bundle / "_internal").mkdir(parents=True)
    (bundle / "BAKLOG.exe").write_bytes(b"MZ")
    (bundle / "BAKLOG Tray.exe").write_bytes(b"MZ")
    (bundle / "_internal" / "helper.exe").write_bytes(b"MZ")
    (bundle / "_internal" / "python311.dll").write_bytes(b"MZ")
    out = tmp_path / "files.txt"

    base = [ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SIGN_SCRIPT)]
    listed = subprocess.run(
        [*base, "-List", "-Root", str(bundle), "-OutFile", str(out)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert listed.returncode == 0, listed.stdout + listed.stderr
    names = sorted(Path(p).name for p in out.read_text(encoding="utf-8").splitlines() if p.strip())
    assert names == ["BAKLOG Tray.exe", "BAKLOG.exe", "helper.exe"]
    assert all(Path(p).is_absolute() for p in out.read_text(encoding="utf-8").splitlines() if p.strip())

    verified = subprocess.run(
        [*base, "-Verify", "-Root", str(bundle)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert verified.returncode != 0
    assert "FAIL" in verified.stdout


@pytest.mark.skipif(sys.platform != "win32", reason="Authenticode helpers are Windows-only")
def test_sign_script_rejects_missing_mode(tmp_path: Path) -> None:
    ps = _powershell()
    if not ps:
        pytest.skip("PowerShell not available")
    result = subprocess.run(
        [ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SIGN_SCRIPT), "-Root", str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode != 0
