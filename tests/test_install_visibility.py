"""Tests for install source + ARP visibility helpers."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from shared.install_visibility import (
    INNO_UNINSTALL_REG_SUFFIX,
    arp_version_mismatch,
    detect_install_source,
    install_visibility_fields,
    read_arp_display_version,
    repair_arp_display_version,
    write_arp_display_version,
)


def test_detect_install_source_dev() -> None:
    with patch("shared.install_visibility.is_frozen", return_value=False):
        assert detect_install_source() == "dev"


def test_detect_install_source_portable(tmp_path: Path) -> None:
    with patch("shared.install_visibility.is_frozen", return_value=True):
        with patch("shared.install_visibility.is_portable_frozen", return_value=True):
            assert detect_install_source() == "portable"


def test_detect_install_source_setup(tmp_path: Path) -> None:
    install = tmp_path / "BAKLOG"
    install.mkdir()
    (install / "unins000.exe").write_bytes(b"stub")
    with patch("shared.install_visibility.is_frozen", return_value=True):
        with patch("shared.install_visibility.is_portable_frozen", return_value=False):
            with patch("shared.install_visibility.frozen_bundle_dir", return_value=install):
                with patch("shared.install_visibility.sys.platform", "win32"):
                    assert detect_install_source() == "setup"


def test_detect_install_source_zip(tmp_path: Path) -> None:
    install = tmp_path / "BAKLOG"
    install.mkdir()
    with patch("shared.install_visibility.is_frozen", return_value=True):
        with patch("shared.install_visibility.is_portable_frozen", return_value=False):
            with patch("shared.install_visibility.frozen_bundle_dir", return_value=install):
                assert detect_install_source() == "zip"


def test_arp_version_mismatch() -> None:
    assert arp_version_mismatch("0.8.27", "0.8.26") is True
    assert arp_version_mismatch("v0.8.27", "0.8.27") is False
    assert arp_version_mismatch("0.8.27", None) is False


def test_read_arp_display_version_non_windows() -> None:
    with patch("shared.install_visibility.sys.platform", "linux"):
        assert read_arp_display_version() is None


def test_write_arp_display_version_non_windows() -> None:
    with patch("shared.install_visibility.sys.platform", "linux"):
        assert write_arp_display_version("0.9.01") is False


@pytest.mark.skipif(sys.platform != "win32", reason="Windows registry only")
def test_write_arp_display_version_updates_registry() -> None:
    import winreg

    subkey = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{INNO_UNINSTALL_REG_SUFFIX}"
    with patch("shared.install_visibility.sys.platform", "win32"):
        winreg.CreateKey(winreg.HKEY_CURRENT_USER, subkey)
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, "0.8.38")
            assert write_arp_display_version("0.9.01") is True
            assert read_arp_display_version() == "0.9.01"
        finally:
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, subkey)
            except OSError:
                pass


def test_repair_arp_display_version_noop_when_matched() -> None:
    with patch("shared.install_visibility.sys.platform", "win32"):
        with patch("shared.install_visibility.read_arp_display_version", return_value="0.9.22"):
            with patch("shared.install_visibility.write_arp_display_version") as write:
                assert repair_arp_display_version("0.9.22") is False
                write.assert_not_called()


def test_repair_arp_display_version_writes_on_mismatch() -> None:
    with patch("shared.install_visibility.sys.platform", "win32"):
        with patch("shared.install_visibility.read_arp_display_version", return_value="0.9.20"):
            with patch("shared.install_visibility.write_arp_display_version", return_value=True) as write:
                assert repair_arp_display_version("0.9.22") is True
                write.assert_called_once_with("0.9.22")


def test_repair_arp_display_version_noop_without_arp_entry() -> None:
    with patch("shared.install_visibility.sys.platform", "win32"):
        with patch("shared.install_visibility.read_arp_display_version", return_value=None):
            with patch("shared.install_visibility.write_arp_display_version") as write:
                assert repair_arp_display_version("0.9.22") is False
                write.assert_not_called()


def test_run_boot_checks_repairs_arp_version() -> None:
    from shared.server_support import run_boot_checks

    with patch("shared.server_support.is_frozen", return_value=True):
        with patch("shared.server_support.sys.platform", "win32"):
            with patch("shared.server_support.check_data_location"):
                with patch("shared.startup.reconcile_startup", return_value=False):
                    with patch("shared.server_support._read_bundle_version", return_value="0.9.22"):
                        with patch(
                            "shared.install_visibility.repair_arp_display_version",
                            return_value=True,
                        ) as repair:
                            run_boot_checks(Path("/tmp/data"))
                            repair.assert_called_once_with("0.9.22")


def test_install_visibility_fields_includes_keys() -> None:
    with patch("shared.install_visibility.is_frozen", return_value=False):
        with patch("shared.install_visibility.detect_install_source", return_value="zip"):
            with patch("shared.install_visibility.read_arp_display_version", return_value=None):
                fields = install_visibility_fields("1.0.0")
    assert fields == {
        "install_source": "zip",
        "arp_version": None,
        "arp_version_mismatch": False,
    }


def test_install_trust_fields_when_frozen() -> None:
    with patch("shared.install_visibility.is_frozen", return_value=True):
        with patch("shared.install_visibility.sys.platform", "win32"):
            with patch("shared.install_visibility.detect_install_source", return_value="zip"):
                with patch("shared.install_visibility.read_arp_display_version", return_value=None):
                    fields = install_visibility_fields("0.8.27")
    assert fields["unsigned_beta"] is True
    assert "SmartScreen" in fields["trust_note"]


def test_build_diagnostics_payload_includes_install_visibility() -> None:
    from shared.server_support import build_diagnostics_payload

    with patch("shared.install_visibility.detect_install_source", return_value="setup"):
        with patch("shared.install_visibility.read_arp_display_version", return_value="0.8.25"):
            payload = build_diagnostics_payload(
                data_root=Path("/tmp/data"),
                version="0.8.27",
                load_run_history=lambda: [],
            )
    assert payload["install_source"] == "setup"
    assert payload["arp_version"] == "0.8.25"
    assert payload["arp_version_mismatch"] is True
