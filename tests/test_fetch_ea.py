"""Tests for fetch_ea CLI error handling."""
from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock, patch

from clients.ea_client import EaCaptureError


def test_ea_connected_requires_mark_connected_blob(monkeypatch) -> None:
    import fetchers.fetch_ea as fetch_ea

    monkeypatch.setattr("auth.manager.get_provider_blob", lambda _p: {})
    assert fetch_ea._ea_connected() is False

    monkeypatch.setattr(
        "auth.manager.get_provider_blob",
        lambda _p: {"status": "connected", "EA_BEARER_TOKEN": "tok"},
    )
    assert fetch_ea._ea_connected() is True


def test_fetch_blocks_while_auth_session_active(monkeypatch) -> None:
    import fetchers.fetch_ea as fetch_ea

    monkeypatch.setattr("fetchers.fetch_ea._ea_connected", lambda: True)
    monkeypatch.setattr("auth.manager.has_active_sessions", lambda: True)

    with patch("fetchers.fetch_ea._resolve_session") as mock_resolve:
        monkeypatch.setattr(sys, "argv", ["fetch_ea", "--skip-hltb"])
        code = fetch_ea.main()
        mock_resolve.assert_not_called()

    assert code == 1


def test_capture_error_does_not_mark_invalid(tmp_path, monkeypatch) -> None:
    prof = tmp_path / "profiles" / "ea"
    prof.mkdir(parents=True)
    (prof / "Default").mkdir()

    monkeypatch.setattr("fetchers.fetch_ea.profile_dir", lambda _p: prof)
    monkeypatch.setattr("fetchers.fetch_ea._ea_connected", lambda: True)

    mark_calls: list = []

    def fake_mark_invalid(provider: str, *, error: str = "") -> None:
        mark_calls.append((provider, error))

    monkeypatch.setattr("fetchers.fetch_ea.mark_invalid", fake_mark_invalid)

    with patch("fetchers.fetch_ea._resolve_session") as mock_resolve:
        mock_resolve.side_effect = EaCaptureError("capture failed")
        import fetchers.fetch_ea as fetch_ea

        monkeypatch.setattr(sys, "argv", ["fetch_ea", "--skip-hltb"])
        code = fetch_ea.main()

    assert code == 1
    assert mark_calls == []


def test_stored_token_skips_sniff_when_owned_api_works(monkeypatch) -> None:
    monkeypatch.setattr("fetchers.fetch_ea._ea_connected", lambda: True)
    monkeypatch.setattr(
        "fetchers.fetch_ea.resolve_env",
        lambda key, **_k: "stored-tok" if key == "EA_BEARER_TOKEN" else "",
    )
    monkeypatch.setattr(
        "fetchers.fetch_ea.probe_ea_token",
        lambda *_a, **_k: {"ok": True},
    )
    sample_cookies = [{"name": "remid", "value": "x"}]
    monkeypatch.setattr("fetchers.fetch_ea._load_ea_profile_cookies", lambda: sample_cookies)

    class Client:
        def get_owned_games(self):
            return [{"originOfferId": "1", "product": {"name": "Test"}}]

    monkeypatch.setattr("fetchers.fetch_ea.EaClient", lambda *_a, **_k: Client())

    with patch("fetchers.fetch_ea.launch_ea_profile") as mock_launch:
        import fetchers.fetch_ea as fetch_ea

        token, cookies, dbg = fetch_ea._resolve_session(headless=True)
        mock_launch.assert_not_called()

    assert token == "stored-tok"
    assert cookies == sample_cookies
    assert dbg.get("token_source") == "stored"
    assert len(dbg.get("owned_items") or []) == 1


def test_stored_token_browser_fallback_when_apq_stale(monkeypatch, tmp_path) -> None:
    prof = tmp_path / "ea"
    prof.mkdir(parents=True)
    (prof / "Default").mkdir()
    monkeypatch.setattr("fetchers.fetch_ea.profile_dir", lambda _p: prof)
    monkeypatch.setattr("fetchers.fetch_ea._ea_connected", lambda: True)
    monkeypatch.setattr(
        "fetchers.fetch_ea.resolve_env",
        lambda key, **_k: "stored-tok" if key == "EA_BEARER_TOKEN" else "",
    )
    monkeypatch.setattr(
        "fetchers.fetch_ea.probe_ea_token",
        lambda *_a, **_k: {"ok": True, "library_via_browser": True},
    )
    sample_cookies = [{"name": "remid", "value": "x"}]
    monkeypatch.setattr("fetchers.fetch_ea._load_ea_profile_cookies", lambda: sample_cookies)
    monkeypatch.setattr("fetchers.fetch_ea.read_ea_connect_snapshot", lambda **_k: None)

    fake_result = type(
        "R",
        (),
        {
            "token": "stored-tok",
            "cookies": sample_cookies,
            "owned_items": [{"originOfferId": "2", "product": {"name": "Browser"}}],
            "debug": {"final_url": "https://www.ea.com/sales/deals"},
        },
    )()

    ctx = MagicMock()
    ctx.pages = [MagicMock()]
    with patch("fetchers.fetch_ea.launch_ea_profile") as mock_launch, patch(
        "fetchers.fetch_ea.sniff_ea_bearer",
        return_value=fake_result,
    ):
        mock_launch.return_value.__enter__.return_value = ctx
        import fetchers.fetch_ea as fetch_ea

        token, cookies, dbg = fetch_ea._resolve_session(headless=True)

    mock_launch.assert_called_once()
    assert dbg.get("token_source") == "sniff"
    assert len(dbg.get("owned_items") or []) == 1


def test_resolve_session_skips_browser_when_snapshot_fresh(monkeypatch, tmp_path) -> None:
    import fetchers.fetch_ea as fetch_ea
    from datetime import UTC, datetime

    snap = tmp_path / "connect_snapshot.json"
    snap.write_text(
        json.dumps(
            {
                "captured_at": datetime.now(UTC).isoformat(),
                "owned_items": [{"originOfferId": "1", "product": {"name": "Game"}}],
                "browser_auth_ok": True,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("clients.ea_session.ea_connect_snapshot_path", lambda: snap)
    monkeypatch.setattr(fetch_ea, "_load_ea_profile_cookies", lambda: [])

    with patch("fetchers.fetch_ea.launch_ea_profile") as mock_launch:
        token, _cookies, dbg = fetch_ea._resolve_session(headless=True)

    mock_launch.assert_not_called()
    assert dbg.get("token_source") == "connect_snapshot"
    assert token == ""


def test_resolve_session_skips_browser_for_auth_only_snapshot(monkeypatch, tmp_path) -> None:
    import fetchers.fetch_ea as fetch_ea
    from datetime import UTC, datetime

    snap = tmp_path / "connect_snapshot.json"
    snap.write_text(
        json.dumps(
            {
                "captured_at": datetime.now(UTC).isoformat(),
                "owned_items": [],
                "browser_auth_ok": True,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("clients.ea_session.ea_connect_snapshot_path", lambda: snap)
    monkeypatch.setattr(fetch_ea, "_load_ea_profile_cookies", lambda: [{"name": "remid", "value": "x"}])

    with patch("fetchers.fetch_ea.launch_ea_profile") as mock_launch:
        token, cookies, dbg = fetch_ea._resolve_session(headless=True)

    mock_launch.assert_not_called()
    assert dbg.get("token_source") == "connect_snapshot"
    assert dbg.get("connect_snapshot_auth_only") is True
    assert dbg.get("owned_items") == []
    assert cookies
def test_main_session_expired_marks_invalid_exit_4(monkeypatch) -> None:
    import fetchers.fetch_ea as fetch_ea
    from clients.ea_client import EaAuthError
    from fetchers._progress import EXIT_CODE_AUTH

    mark_calls: list = []
    monkeypatch.setattr(fetch_ea, "_ea_connected", lambda: True)
    monkeypatch.setattr("auth.manager.has_active_sessions", lambda: False)
    monkeypatch.setattr(fetch_ea, "mark_invalid", lambda *a, **k: mark_calls.append((a, k)))

    with patch("fetchers.fetch_ea._resolve_session") as mock_resolve:
        mock_resolve.side_effect = EaAuthError("EA session expired")
        monkeypatch.setattr(sys, "argv", ["fetch_ea", "--skip-hltb"])
        code = fetch_ea.main()

    assert code == EXIT_CODE_AUTH
    assert mark_calls


def test_main_empty_owned_exit_4(monkeypatch) -> None:
    import fetchers.fetch_ea as fetch_ea
    from fetchers._progress import EXIT_CODE_AUTH

    monkeypatch.setattr(fetch_ea, "_ea_connected", lambda: True)
    monkeypatch.setattr("auth.manager.has_active_sessions", lambda: False)
    monkeypatch.setattr(fetch_ea, "mark_invalid", lambda *_a, **_k: None)

    with patch("fetchers.fetch_ea._resolve_session") as mock_resolve, patch(
        "fetchers.fetch_ea.fetch_owned_games_browser",
        return_value=[],
    ):
        mock_resolve.return_value = ("", [], {"owned_items": []})
        monkeypatch.setattr(sys, "argv", ["fetch_ea", "--skip-hltb"])
        code = fetch_ea.main()

    assert code == EXIT_CODE_AUTH


def test_cdp_closed_is_exit_1_not_4(monkeypatch) -> None:
    import fetchers.fetch_ea as fetch_ea

    monkeypatch.setattr(fetch_ea, "_ea_connected", lambda: True)
    monkeypatch.setattr("auth.manager.has_active_sessions", lambda: False)

    def boom(*_a, **_k):
        raise RuntimeError("CDP connection closed")

    with patch("fetchers.fetch_ea._resolve_session", side_effect=boom), patch(
        "fetchers.fetch_ea.mark_invalid",
        side_effect=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("should not mark invalid")),
    ):
        monkeypatch.setattr(sys, "argv", ["fetch_ea", "--skip-hltb"])
        code = fetch_ea.main()

    assert code == 1
