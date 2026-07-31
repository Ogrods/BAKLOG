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


@pytest.mark.skipif(sys.platform != "win32", reason="Windows apply script only")
def test_apply_update_ps1_replaces_install_and_writes_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    update_root = tmp_path / "BAKLOG-update"
    update_root.mkdir()
    monkeypatch.setenv("TEMP", str(tmp_path))
    monkeypatch.setenv("TMP", str(tmp_path))

    install = tmp_path / "install" / "BAKLOG"
    install.mkdir(parents=True)
    (install / "BAKLOG.exe").write_bytes(b"old-server")
    (install / "BAKLOG Tray.exe").write_bytes(b"old-tray")
    (install / "old.txt").write_text("keep-me-gone", encoding="utf-8")

    bundle = tmp_path / "bundle" / "BAKLOG"
    bundle.mkdir(parents=True)
    (bundle / "BAKLOG.exe").write_bytes(b"new-server")
    (bundle / "BAKLOG Tray.exe").write_bytes(b"new-tray")
    (bundle / "apply_update.ps1").write_text("# new", encoding="utf-8")
    (bundle / "fresh.txt").write_text("from-update", encoding="utf-8")

    version = "9.9.9-test"
    version_dir = update_root / version
    version_dir.mkdir()
    zip_path = version_dir / "package.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for path in bundle.rglob("*"):
            if path.is_file():
                zf.write(path, arcname=str(Path("BAKLOG") / path.relative_to(bundle)))

    sha256 = hashlib.sha256(zip_path.read_bytes()).hexdigest()
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

    # Avoid launching the fake tray binary via Start-Process.
    script_text = APPLY_PS1.read_text(encoding="utf-8")
    patched = script_text.replace(
        "Start-Process -FilePath $trayExePath -WorkingDirectory $installDir | Out-Null",
        "# test harness: skip Start-Process",
    )
    harness = tmp_path / "apply_harness.ps1"
    harness.write_text(patched, encoding="utf-8")

    proc = subprocess.run(
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
    assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"

    assert (install / "BAKLOG.exe").read_bytes() == b"new-server"
    assert (install / "BAKLOG Tray.exe").read_bytes() == b"new-tray"
    assert (install / "fresh.txt").read_text(encoding="utf-8") == "from-update"
    # Overlay copy keeps install-only files; full wipe is not part of apply.
    assert (install / "old.txt").read_text(encoding="utf-8") == "keep-me-gone"

    result_path = update_root / "apply-result.json"
    assert result_path.is_file()
    result = json.loads(result_path.read_text(encoding="utf-8-sig"))
    assert result["ok"] is True
    assert result["version"] == version
    assert not (update_root / "applying.lock").exists()
