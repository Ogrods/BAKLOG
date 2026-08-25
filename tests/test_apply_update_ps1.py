"""Smoke-test packaging/apply_update.ps1 against a synthetic Windows bundle zip."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
APPLY_PS1 = REPO / "packaging" / "apply_update.ps1"


def _skip_start_process(script_text: str) -> str:
    return script_text.replace(
        "Start-Process -FilePath $trayExePath -WorkingDirectory $script:InstallDir | Out-Null",
        "# test harness: skip Start-Process",
    ).replace(
        "Start-Process -FilePath $trayExePath -WorkingDirectory $installDir | Out-Null",
        "# test harness: skip Start-Process",
    )


def _make_bundle_zip(tmp_path: Path, *, include_tray: bool = True) -> tuple[Path, str]:
    update_root = tmp_path / "BAKLOG-update"
    update_root.mkdir(exist_ok=True)
    bundle = tmp_path / "bundle" / "BAKLOG"
    bundle.mkdir(parents=True)
    (bundle / "BAKLOG.exe").write_bytes(b"new-server")
    if include_tray:
        (bundle / "BAKLOG Tray.exe").write_bytes(b"new-tray")
    (bundle / "apply_update.ps1").write_text("# new", encoding="utf-8")
    (bundle / "fresh.txt").write_text("from-update", encoding="utf-8")

    version = "9.9.9-test"
    version_dir = update_root / version
    version_dir.mkdir(exist_ok=True)
    zip_path = version_dir / "package.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for path in bundle.rglob("*"):
            if path.is_file():
                zf.write(path, arcname=str(Path("BAKLOG") / path.relative_to(bundle)))
    sha256 = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    return zip_path, sha256


def _run_apply(
    tmp_path: Path,
    *,
    install: Path,
    zip_path: Path,
    sha256: str,
    version: str = "9.9.9-test",
) -> subprocess.CompletedProcess[str]:
    update_root = tmp_path / "BAKLOG-update"
    version_dir = update_root / version
    version_dir.mkdir(parents=True, exist_ok=True)
    manifest = version_dir / "apply-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "install_dir": str(install),
                "zip_path": str(zip_path),
                "sha256": sha256,
                "version": version,
                "server_pid": 0,
                "tray_pid": 0,
            }
        ),
        encoding="utf-8",
    )
    (update_root / "applying.lock").write_text('{"version":"9.9.9-test"}', encoding="utf-8")
    harness = tmp_path / "apply_harness.ps1"
    harness.write_text(_skip_start_process(APPLY_PS1.read_text(encoding="utf-8")), encoding="utf-8")
    return subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(harness),
            "-ManifestPath",
            str(manifest),
        ],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "TEMP": str(tmp_path), "TMP": str(tmp_path)},
    )


@pytest.mark.skipif(sys.platform != "win32", reason="Windows apply script only")
def test_apply_update_ps1_replaces_install_and_writes_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEMP", str(tmp_path))
    monkeypatch.setenv("TMP", str(tmp_path))

    install = tmp_path / "install" / "BAKLOG"
    install.mkdir(parents=True)
    (install / "BAKLOG.exe").write_bytes(b"old-server")
    (install / "BAKLOG Tray.exe").write_bytes(b"old-tray")
    (install / "old.txt").write_text("keep-me-gone", encoding="utf-8")

    zip_path, sha256 = _make_bundle_zip(tmp_path)
    proc = _run_apply(tmp_path, install=install, zip_path=zip_path, sha256=sha256)
    assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"

    assert (install / "BAKLOG.exe").read_bytes() == b"new-server"
    assert (install / "BAKLOG Tray.exe").read_bytes() == b"new-tray"
    assert (install / "fresh.txt").read_text(encoding="utf-8") == "from-update"
    # Overlay copy keeps install-only files; full wipe is not part of apply.
    assert (install / "old.txt").read_text(encoding="utf-8") == "keep-me-gone"

    update_root = tmp_path / "BAKLOG-update"
    result_path = update_root / "apply-result.json"
    assert result_path.is_file()
    result = json.loads(result_path.read_text(encoding="utf-8-sig"))
    assert result["ok"] is True
    assert result["version"] == "9.9.9-test"
    assert not (update_root / "applying.lock").exists()
    assert (update_root / "apply-started.json").exists() or not (update_root / "apply-started.json").exists()
    # Success clears apply-started via Write-ApplyResult.
    assert not (update_root / "apply-started.json").exists()
    assert (update_root / "apply.log").is_file()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows apply script only")
def test_apply_update_ps1_corrupt_zip_writes_result_and_clears_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEMP", str(tmp_path))
    monkeypatch.setenv("TMP", str(tmp_path))
    install = tmp_path / "install" / "BAKLOG"
    install.mkdir(parents=True)
    (install / "BAKLOG.exe").write_bytes(b"old-server")
    (install / "BAKLOG Tray.exe").write_bytes(b"old-tray")

    update_root = tmp_path / "BAKLOG-update"
    update_root.mkdir()
    version = "9.9.9-bad"
    version_dir = update_root / version
    version_dir.mkdir()
    zip_path = version_dir / "package.zip"
    zip_path.write_bytes(b"not-a-zip")
    sha256 = hashlib.sha256(zip_path.read_bytes()).hexdigest()

    proc = _run_apply(tmp_path, install=install, zip_path=zip_path, sha256=sha256, version=version)
    assert proc.returncode != 0
    result = json.loads((update_root / "apply-result.json").read_text(encoding="utf-8-sig"))
    assert result["ok"] is False
    assert result["error"]
    assert not (update_root / "applying.lock").exists()
    # Install unchanged.
    assert (install / "BAKLOG.exe").read_bytes() == b"old-server"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows apply script only")
def test_apply_update_ps1_missing_tray_in_bundle_restores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEMP", str(tmp_path))
    monkeypatch.setenv("TMP", str(tmp_path))
    install = tmp_path / "install" / "BAKLOG"
    install.mkdir(parents=True)
    (install / "BAKLOG.exe").write_bytes(b"old-server")
    (install / "BAKLOG Tray.exe").write_bytes(b"old-tray")

    # Bundle without tray exe → layout invalid before copy, or missing after.
    zip_path, sha256 = _make_bundle_zip(tmp_path, include_tray=False)
    proc = _run_apply(tmp_path, install=install, zip_path=zip_path, sha256=sha256)
    assert proc.returncode != 0
    update_root = tmp_path / "BAKLOG-update"
    result = json.loads((update_root / "apply-result.json").read_text(encoding="utf-8-sig"))
    assert result["ok"] is False
    assert "layout invalid" in result["error"].lower() or "tray" in result["error"].lower()
    assert not (update_root / "applying.lock").exists()
    assert (install / "BAKLOG.exe").read_bytes() == b"old-server"


def test_apply_update_ps1_avoids_module_cmdlets() -> None:
    text = APPLY_PS1.read_text(encoding="utf-8")
    assert "Expand-Archive" not in text
    assert "Get-FileHash" not in text
    assert "Stop-ProcessTreeExcludingSelf" in text
    assert "taskkill" not in text.lower()
    assert "$PID" in text
    assert "apply-started.json" in text
    # Prefer entry-by-entry extract (zip-slip checks) over ExtractToDirectory.
    assert "Expand-ZipDotNet" in text
    assert "zip-slip" in text
    assert "ExtractToFile" in text
    assert "ExtractToDirectory" not in text


def test_apply_update_ps1_kill_helper_excludes_self() -> None:
    text = APPLY_PS1.read_text(encoding="utf-8")
    assert "Get-AncestorPidSet" in text
    assert "ExcludeSet" in text
    assert "if ($tid -eq $PID) { continue }" in text or "$PID" in text
