from pathlib import Path
from unittest.mock import patch

from shared.install_visibility import (
    arp_version_mismatch,
    detect_install_source,
    install_visibility_fields,
    read_arp_display_version,
)


def test_detect_install_source_dev():
    with patch("shared.install_visibility.is_frozen", return_value=False):
        assert detect_install_source() == "dev"


def test_detect_install_source_portable(tmp_path):
    with patch("shared.install_visibility.is_frozen", return_value=True):
        with patch("shared.install_visibility.is_portable_frozen", return_value=True):
            assert detect_install_source() == "portable"


def test_detect_install_source_setup(tmp_path):
    install = tmp_path / "BAKLOG"
    install.mkdir()
    (install / "unins000.exe").write_bytes(b"stub")
    with patch("shared.install_visibility.is_frozen", return_value=True):
        with patch("shared.install_visibility.is_portable_frozen", return_value=False):
            with patch("shared.install_visibility.frozen_bundle_dir", return_value=install):
                with patch("shared.install_visibility.sys.platform", "win32"):
                    assert detect_install_source() == "setup"


def test_detect_install_source_zip(tmp_path):
    install = tmp_path / "BAKLOG"
    install.mkdir()
    with patch("shared.install_visibility.is_frozen", return_value=True):
        with patch("shared.install_visibility.is_portable_frozen", return_value=False):
            with patch("shared.install_visibility.frozen_bundle_dir", return_value=install):
                assert detect_install_source() == "zip"


def test_arp_version_mismatch():
    assert arp_version_mismatch("0.8.27", "0.8.26") is True
    assert arp_version_mismatch("v0.8.27", "0.8.27") is False
    assert arp_version_mismatch("0.8.27", None) is False


def test_read_arp_display_version_non_windows():
    with patch("shared.install_visibility.sys.platform", "linux"):
        assert read_arp_display_version() is None


def test_install_visibility_fields_includes_keys():
    with patch("shared.install_visibility.is_frozen", return_value=False):
        with patch("shared.install_visibility.detect_install_source", return_value="zip"):
            with patch("shared.install_visibility.read_arp_display_version", return_value=None):
                fields = install_visibility_fields("1.0.0")
    assert fields == {"install_source": "zip", "arp_version": None, "arp_version_mismatch": False}


def test_install_trust_fields_when_frozen():
    with patch("shared.install_visibility.is_frozen", return_value=True):
        with patch("shared.install_visibility.sys.platform", "win32"):
            with patch("shared.install_visibility.detect_install_source", return_value="zip"):
                with patch("shared.install_visibility.read_arp_display_version", return_value=None):
                    fields = install_visibility_fields("0.8.27")
    assert fields["unsigned_beta"] is True
    assert "SmartScreen" in fields["trust_note"]


def test_build_diagnostics_payload_includes_install_visibility():
    from shared.server_support import build_diagnostics_payload

    with patch("shared.install_visibility.detect_install_source", return_value="setup"):
        with patch("shared.install_visibility.read_arp_display_version", return_value="0.8.25"):
            payload = build_diagnostics_payload(
                data_root=Path("/tmp/data"), version="0.8.27", load_run_history=lambda: []
            )
    assert payload["install_source"] == "setup"
    assert payload["arp_version"] == "0.8.25"
    assert payload["arp_version_mismatch"] is True
