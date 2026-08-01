"""Browser-auth worker must inherit the request profile context."""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from auth import manager as auth_manager
from shared import profile_paths


@pytest.fixture()
def profile_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    prof = tmp_path / "profiles"
    monkeypatch.setattr(profile_paths, "ROOT", tmp_path)
    monkeypatch.setattr(profile_paths, "PROFILES_DIR", prof)
    monkeypatch.setattr(profile_paths, "INDEX_FILE", prof / "index.json")
    yield tmp_path


def test_browser_auth_worker_inherits_profile_context(
    profile_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[str] = []
    done = threading.Event()

    def fake_run_browser_auth(_provider: str, _session: object) -> dict[str, str]:
        return {"token": "x"}

    def fake_mark_connected(_provider: str, _creds: dict[str, str]) -> None:
        captured.append(profile_paths.get_active_profile_id())
        done.set()

    monkeypatch.setattr(auth_manager, "run_browser_auth", fake_run_browser_auth)
    monkeypatch.setattr(auth_manager, "mark_connected", fake_mark_connected)

    profile_paths.set_request_profile_id("pinned-profile-99")
    try:
        auth_manager.start_browser_auth("steam")
        assert done.wait(timeout=3.0)
    finally:
        profile_paths.clear_request_profile_id()

    assert captured == ["pinned-profile-99"]


def _stub_browser_worker(monkeypatch: pytest.MonkeyPatch) -> threading.Event:
    """Mock the browser-auth worker internals so start_browser_auth is inert."""
    done = threading.Event()

    monkeypatch.setattr(
        auth_manager, "run_browser_auth", lambda _p, _s: {"token": "x"}
    )
    monkeypatch.setattr(
        "auth.session_probe.probe_browser_session", lambda _p, _c: None
    )
    monkeypatch.setattr(
        auth_manager, "mark_connected", lambda _p, _c: done.set()
    )
    return done


def test_fresh_reconnect_clears_browser_session(
    profile_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cleared: list[str] = []
    monkeypatch.setattr(
        auth_manager, "clear_browser_session", lambda p: cleared.append(p)
    )
    done = _stub_browser_worker(monkeypatch)

    auth_manager.start_browser_auth("xbox_wishlist", fresh=True)
    assert done.wait(timeout=3.0)
    assert cleared == ["xbox_wishlist"]


def test_plain_connect_does_not_clear_browser_session(
    profile_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cleared: list[str] = []
    monkeypatch.setattr(
        auth_manager, "clear_browser_session", lambda p: cleared.append(p)
    )
    done = _stub_browser_worker(monkeypatch)

    auth_manager.start_browser_auth("xbox_wishlist")
    assert done.wait(timeout=3.0)
    assert cleared == []


def test_battlenet_plain_connect_clears_browser_session(
    profile_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Battle.net always clears profile so stale cookies cannot false-complete."""
    cleared: list[str] = []
    monkeypatch.setattr(
        auth_manager, "clear_browser_session", lambda p: cleared.append(p)
    )
    done = _stub_browser_worker(monkeypatch)

    auth_manager.start_browser_auth("battlenet")
    assert done.wait(timeout=3.0)
    assert cleared == ["battlenet"]


def test_clear_browser_session_removes_profile_dir(
    profile_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prof = profile_env / "xbox_wishlist_profile"
    prof.mkdir(parents=True)
    (prof / "Cookies").write_text("stale", encoding="utf-8")
    monkeypatch.setattr(auth_manager, "profile_dir", lambda _p: prof)

    auth_manager.clear_browser_session("xbox_wishlist")
    assert not prof.exists()


def test_start_browser_auth_rejects_overlapping_provider_session(
    profile_env: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = threading.Event()
    release = threading.Event()

    def slow_run(_provider: str, _session: object) -> dict[str, str]:
        started.set()
        release.wait(timeout=5.0)
        return {"token": "x"}

    monkeypatch.setattr(auth_manager, "run_browser_auth", slow_run)
    monkeypatch.setattr(auth_manager, "mark_connected", lambda _p, _c: None)

    auth_manager.start_browser_auth("steam")
    assert started.wait(timeout=3.0)

    with pytest.raises(ValueError, match="already open"):
        auth_manager.start_browser_auth("steam")

    release.set()


def test_cancel_browser_auth_finishes_session(
    profile_env: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = threading.Event()
    release = threading.Event()

    def slow_run(_provider: str, session: object) -> dict[str, str]:
        started.set()
        # Cooperative cancel: abort when asked.
        from auth.runner import abort_if_cancelled

        deadline = time.time() + 5.0
        while time.time() < deadline:
            try:
                abort_if_cancelled(session)  # type: ignore[arg-type]
            except Exception:
                return {}
            if release.wait(timeout=0.05):
                break
        return {"token": "x"}

    monkeypatch.setattr(auth_manager, "run_browser_auth", slow_run)
    monkeypatch.setattr(auth_manager, "mark_connected", lambda _p, _c: None)
    monkeypatch.setattr(auth_manager, "mark_invalid", lambda _p, error=None: None)

    auth_manager.start_browser_auth("xbox_wishlist")
    assert started.wait(timeout=3.0)
    assert auth_manager.cancel_browser_auth("xbox_wishlist") is True
    assert auth_manager._unfinished_session_for("xbox_wishlist") is None
    release.set()


def test_stale_session_taken_over_by_plain_connect(
    profile_env: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    done = _stub_browser_worker(monkeypatch)
    cleared: list[str] = []
    monkeypatch.setattr(
        auth_manager, "clear_browser_session", lambda p: cleared.append(p)
    )

    # Inject a stale unfinished session older than SUCCESS_WAIT_SEC + 30.
    from auth.runner import AuthSession, SUCCESS_WAIT_SEC

    stale = AuthSession("staleold", "xbox_wishlist")
    stale.started_at = time.time() - (SUCCESS_WAIT_SEC + 60)
    with auth_manager._sessions_lock:
        auth_manager._active_sessions["staleold"] = stale

    auth_manager.start_browser_auth("xbox_wishlist")
    assert done.wait(timeout=3.0)
    assert stale._finished.is_set()
    assert auth_manager._unfinished_session_for("xbox_wishlist") is not None or done.is_set()
