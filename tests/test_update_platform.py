"""Platform parity for in-app update artifacts and apply launcher."""

from __future__ import annotations

from pathlib import Path

import pytest

from shared.update_platform import (
    apply_script_name,
    is_in_app_apply_platform,
    launch_apply_subprocess,
    required_bundle_files,
    server_binary_name,
    stable_sha256_name,
    stable_zip_name,
    tray_binary_name,
)
from shared.update_release import is_allowed_download_url


@pytest.mark.parametrize(
    ("platform", "zip_name", "sha_name", "server", "tray", "script"),
    [
        ("win32", "BAKLOG-win64.zip", "BAKLOG-win64.sha256", "BAKLOG.exe", "BAKLOG Tray.exe", "apply_update.ps1"),
        ("darwin", "BAKLOG-macos.zip", "BAKLOG-macos.sha256", "BAKLOG", "BAKLOG Tray", "apply_update.sh"),
    ],
)
def test_platform_constants(platform, zip_name, sha_name, server, tray, script) -> None:
    assert stable_zip_name(platform) == zip_name
    assert stable_sha256_name(platform) == sha_name
    assert server_binary_name(platform) == server
    assert tray_binary_name(platform) == tray
    assert apply_script_name(platform) == script
    assert required_bundle_files(platform) == (server, tray)


@pytest.mark.parametrize(
    "platform",
    ["win32", "darwin"],
)
def test_is_in_app_apply_platform(platform, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.platform", platform)
    assert is_in_app_apply_platform() is True


def test_allowed_download_urls_for_macos_asset() -> None:
    url = "https://github.com/Ogrods/BAKLOG/releases/download/v0.8.26/BAKLOG-macos.zip"
    assert is_allowed_download_url(url) is True


@pytest.mark.no_leak_check
def test_launch_apply_subprocess_darwin(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("shared.update_platform.sys.platform", "darwin")
    script = tmp_path / "apply_update.sh"
    script.write_text("#!/bin/bash\n", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    install = tmp_path / "install"
    install.mkdir()
    calls: list[list[str]] = []

    class FakePopen:
        def __init__(self, cmd, **kwargs):
            calls.append(cmd)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr("shared.update_platform.subprocess.Popen", FakePopen)
    launch_apply_subprocess(script=script, manifest_path=manifest, install_dir=install)
    assert calls
    assert calls[0][0] == "/bin/bash"
    assert str(script) in calls[0]


@pytest.mark.no_leak_check
def test_launch_apply_subprocess_win32(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("shared.update_platform.sys.platform", "win32")
    script = tmp_path / "apply_update.ps1"
    script.write_text("param()", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    install = tmp_path / "install"
    install.mkdir()
    calls: list[list[str]] = []

    class FakePopen:
        def __init__(self, cmd, **kwargs):
            calls.append(cmd)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr("shared.update_platform.subprocess.Popen", FakePopen)
    launch_apply_subprocess(script=script, manifest_path=manifest, install_dir=install)
    assert calls
    assert "powershell.exe" in calls[0]
    assert "-ManifestPath" in calls[0]
