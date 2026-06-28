import sys
from unittest.mock import patch

from shared.server_support import build_update_check_payload, normalize_version_tag, update_available


def test_normalize_version_tag_strips_v_prefix():
    assert normalize_version_tag("v0.8.26") == "0.8.26"


def test_update_available_compares_semver_tuple():
    assert update_available("0.8.25", "0.8.26") is True
    assert update_available("0.8.26", "0.8.26") is False
    assert update_available("0.9.0", "0.8.99") is False


def test_build_update_check_payload_ok():
    release = {
        "tag_name": "v1.2.3",
        "html_url": "https://github.com/Ogrods/BAKLOG/releases/tag/v1.2.3",
        "body": "## Notes\n- fix bug",
        "published_at": "2026-06-26T00:00:00Z",
        "assets": [
            {
                "name": "BAKLOG-win64.zip",
                "browser_download_url": "https://github.com/Ogrods/BAKLOG/releases/download/v1.2.3/BAKLOG-win64.zip",
            },
            {
                "name": "BAKLOG-win64.sha256",
                "browser_download_url": "https://github.com/Ogrods/BAKLOG/releases/download/v1.2.3/BAKLOG-win64.sha256",
            },
        ],
    }
    with patch("shared.server_support.fetch_latest_github_release", return_value=release):
        with patch("shared.server_support.is_frozen", return_value=True):
            with patch("shared.update_platform.is_in_app_apply_platform", return_value=True):
                with patch("shared.install_paths.runtime_label", return_value="installed"):
                    with patch("shared.server_support._apply_script_present", return_value=True):
                        with patch("shared.server_support.is_running_from_temp_dir", return_value=False):
                            with patch(
                                "shared.update_release._fetch_text_asset", return_value="a" * 64 + "  BAKLOG-win64.zip"
                            ):
                                payload = build_update_check_payload("1.2.0")
    assert payload["update_available"] is True
    assert payload["latest"] == "1.2.3"
    assert payload["release_notes"] == "## Notes\n- fix bug"
    assert payload["published_at"] == "2026-06-26T00:00:00Z"
    assert payload["download_url"].endswith("BAKLOG-win64.zip")
    assert payload["apply_supported"] is True
    assert payload["apply_blocked_reason"] is None


def test_build_update_check_payload_darwin_without_mac_asset(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    release = {
        "tag_name": "v1.2.3",
        "html_url": "https://github.com/Ogrods/BAKLOG/releases/tag/v1.2.3",
        "assets": [
            {
                "name": "BAKLOG-win64.zip",
                "browser_download_url": "https://github.com/Ogrods/BAKLOG/releases/download/v1.2.3/BAKLOG-win64.zip",
            }
        ],
    }
    with patch("shared.server_support.fetch_latest_github_release", return_value=release):
        with patch("shared.server_support.is_frozen", return_value=True):
            with patch("shared.install_paths.runtime_label", return_value="installed"):
                with patch("shared.server_support._apply_script_present", return_value=True):
                    with patch("shared.server_support.is_running_from_temp_dir", return_value=False):
                        payload = build_update_check_payload("1.2.0")
    assert payload["update_available"] is True
    assert payload["download_url"] is None
    assert payload["apply_supported"] is False
    assert payload["apply_blocked_reason"] == "platform_zip_missing"
    assert payload["apply_blocked_message"]


def test_build_update_check_payload_soft_failure():
    with patch("shared.server_support.fetch_latest_github_release", side_effect=RuntimeError("offline")):
        payload = build_update_check_payload("1.0.0")
    assert payload["update_available"] is False
    assert payload["error"] == "offline"


def test_build_update_check_payload_sign_in_active():
    with patch("shared.server_support.fetch_latest_github_release", side_effect=RuntimeError("offline")):
        payload = build_update_check_payload("1.0.0", sign_in_active=True)
    assert payload["sign_in_active"] is True
    assert payload["fetchers_in_flight"] is False
