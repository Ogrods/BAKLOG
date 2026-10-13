"""Tests for shared/server_support update-check helpers."""
from __future__ import annotations

import io
import json
import sys
from unittest.mock import patch

import pytest

from shared.server_support import (
    build_update_check_payload,
    fetch_latest_github_release,
    github_releases_latest_api_url,
    normalize_version_tag,
    update_available,
)


def _fake_urlopen(payload: dict):
    def _open(req, timeout=None):
        return io.BytesIO(json.dumps(payload).encode("utf-8"))

    return _open


def test_releases_api_url_is_latest_endpoint() -> None:
    assert github_releases_latest_api_url().endswith("/releases/latest")


@pytest.mark.parametrize(
    "flags",
    [{"draft": True}, {"prerelease": True}, {"draft": True, "prerelease": True}],
)
def test_fetch_latest_ignores_draft_and_prerelease(flags: dict) -> None:
    release = {"tag_name": "v99.0.0", **flags}
    with patch("urllib.request.urlopen", _fake_urlopen(release)):
        assert fetch_latest_github_release() == {}


def test_fetch_latest_returns_stable_release() -> None:
    release = {"tag_name": "v99.0.0", "draft": False, "prerelease": False}
    with patch("urllib.request.urlopen", _fake_urlopen(release)):
        assert fetch_latest_github_release() == release


def test_draft_release_never_reports_update() -> None:
    release = {"tag_name": "v99.0.0", "draft": True, "assets": []}
    with patch("urllib.request.urlopen", _fake_urlopen(release)):
        payload = build_update_check_payload("0.9.02")
    assert payload["update_available"] is False
    assert payload["latest"] is None


def test_normalize_version_tag_strips_v_prefix() -> None:
    assert normalize_version_tag("v0.8.26") == "0.8.26"


def test_update_available_compares_semver_tuple() -> None:
    assert update_available("0.8.25", "0.8.26") is True
    assert update_available("0.8.26", "0.8.26") is False
    assert update_available("0.9.0", "0.8.99") is False


def test_build_update_check_payload_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
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
                                "shared.update_release._fetch_text_asset",
                                return_value="a" * 64 + "  BAKLOG-win64.zip",
                            ):
                                payload = build_update_check_payload("1.2.0")
    assert payload["update_available"] is True
    assert payload["latest"] == "1.2.3"
    assert payload["release_notes"] == "## Notes\n- fix bug"
    assert payload["published_at"] == "2026-06-26T00:00:00Z"
    assert payload["download_url"] is not None
    assert payload["download_url"].endswith("BAKLOG-win64.zip")
    assert payload["apply_supported"] is True
    assert payload["apply_blocked_reason"] is None


def test_build_update_check_payload_darwin_without_mac_asset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    release = {
        "tag_name": "v1.2.3",
        "html_url": "https://github.com/Ogrods/BAKLOG/releases/tag/v1.2.3",
        "assets": [
            {
                "name": "BAKLOG-win64.zip",
                "browser_download_url": "https://github.com/Ogrods/BAKLOG/releases/download/v1.2.3/BAKLOG-win64.zip",
            },
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


def test_build_update_check_payload_soft_failure() -> None:
    with patch("shared.server_support.fetch_latest_github_release", side_effect=RuntimeError("offline")):
        payload = build_update_check_payload("1.0.0")
    assert payload["update_available"] is False
    assert payload["error"] == "offline"


def test_build_update_check_payload_sign_in_active() -> None:
    with patch("shared.server_support.fetch_latest_github_release", side_effect=RuntimeError("offline")):
        payload = build_update_check_payload("1.0.0", sign_in_active=True)
    assert payload["sign_in_active"] is True
    assert payload["fetchers_in_flight"] is False
