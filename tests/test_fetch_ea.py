"""Tests for fetch_ea CLI error handling."""
from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

from ea_client import EaCaptureError


def test_capture_error_does_not_mark_invalid(tmp_path, monkeypatch) -> None:
    prof = tmp_path / "profiles" / "ea"
    prof.mkdir(parents=True)
    (prof / "Default").mkdir()

    monkeypatch.setattr("fetch_ea.profile_dir", lambda _p: prof)
    monkeypatch.setattr("fetch_ea._ea_connected", lambda: True)

    mark_calls: list = []

    def fake_mark_invalid(provider: str, *, error: str = "") -> None:
        mark_calls.append((provider, error))

    monkeypatch.setattr("fetch_ea.mark_invalid", fake_mark_invalid)

    with patch("fetch_ea._resolve_session") as mock_resolve:
        mock_resolve.side_effect = EaCaptureError("capture failed")
        import fetch_ea

        monkeypatch.setattr(sys, "argv", ["fetch_ea", "--skip-hltb"])
        code = fetch_ea.main()

    assert code == 1
    assert mark_calls == []


def test_stored_token_skips_sniff(monkeypatch) -> None:
    monkeypatch.setattr("fetch_ea._ea_connected", lambda: True)
    monkeypatch.setattr("fetch_ea.resolve_env", lambda key, **_k: "stored-tok" if key == "EA_BEARER_TOKEN" else "")
    monkeypatch.setattr("fetch_ea.probe_ea_token", lambda *_a, **_k: {"ok": True})

    with patch("auth.cdp_browser.launch_persistent_profile") as mock_launch:
        import fetch_ea

        token, cookies, dbg = fetch_ea._resolve_session(headless=True)
        mock_launch.assert_not_called()

    assert token == "stored-tok"
    assert cookies == []
    assert dbg.get("token_source") == "stored"
