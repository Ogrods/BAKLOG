"""Tests for shared/server_support update-check helpers."""
from __future__ import annotations

from unittest.mock import patch

from shared.server_support import (
    build_update_check_payload,
    normalize_version_tag,
    update_available,
)


def test_normalize_version_tag_strips_v_prefix() -> None:
    assert normalize_version_tag("v0.8.26") == "0.8.26"


def test_update_available_compares_semver_tuple() -> None:
    assert update_available("0.8.25", "0.8.26") is True
    assert update_available("0.8.26", "0.8.26") is False
    assert update_available("0.9.0", "0.8.99") is False


def test_build_update_check_payload_ok() -> None:
    with patch("shared.server_support.fetch_latest_github_release") as mock_release:
        mock_release.return_value = {
            "tag_name": "v1.2.3",
            "html_url": "https://github.com/Ogrods/baklog/releases/tag/v1.2.3",
        }
        payload = build_update_check_payload("1.2.0")
    assert payload["update_available"] is True
    assert payload["latest"] == "1.2.3"
    assert payload["current"] == "1.2.0"
    assert payload["url"].endswith("v1.2.3")


def test_build_update_check_payload_soft_failure() -> None:
    with patch("shared.server_support.fetch_latest_github_release", side_effect=RuntimeError("offline")):
        payload = build_update_check_payload("1.0.0")
    assert payload["update_available"] is False
    assert payload["error"] == "offline"
