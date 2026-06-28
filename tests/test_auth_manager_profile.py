import threading

import pytest

from auth import manager as auth_manager
from shared import profile_paths


@pytest.fixture()
def profile_env(tmp_path, monkeypatch):
    prof = tmp_path / "profiles"
    monkeypatch.setattr(profile_paths, "ROOT", tmp_path)
    monkeypatch.setattr(profile_paths, "PROFILES_DIR", prof)
    monkeypatch.setattr(profile_paths, "INDEX_FILE", prof / "index.json")
    yield tmp_path


def test_browser_auth_worker_inherits_profile_context(profile_env, monkeypatch):
    captured = []
    done = threading.Event()

    def fake_run_browser_auth(_provider, _session):
        return {"token": "x"}

    def fake_mark_connected(_provider, _creds):
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


def _stub_browser_worker(monkeypatch):
    done = threading.Event()
    monkeypatch.setattr(auth_manager, "run_browser_auth", lambda _p, _s: {"token": "x"})
    monkeypatch.setattr("auth.session_probe.probe_browser_session", lambda _p, _c: None)
    monkeypatch.setattr(auth_manager, "mark_connected", lambda _p, _c: done.set())
    return done


def test_fresh_reconnect_clears_browser_session(profile_env, monkeypatch):
    cleared = []
    monkeypatch.setattr(auth_manager, "clear_browser_session", lambda p: cleared.append(p))
    done = _stub_browser_worker(monkeypatch)
    auth_manager.start_browser_auth("xbox_wishlist", fresh=True)
    assert done.wait(timeout=3.0)
    assert cleared == ["xbox_wishlist"]


def test_plain_connect_does_not_clear_browser_session(profile_env, monkeypatch):
    cleared = []
    monkeypatch.setattr(auth_manager, "clear_browser_session", lambda p: cleared.append(p))
    done = _stub_browser_worker(monkeypatch)
    auth_manager.start_browser_auth("xbox_wishlist")
    assert done.wait(timeout=3.0)
    assert cleared == []


def test_clear_browser_session_removes_profile_dir(profile_env, monkeypatch):
    prof = profile_env / "xbox_wishlist_profile"
    prof.mkdir(parents=True)
    (prof / "Cookies").write_text("stale", encoding="utf-8")
    monkeypatch.setattr(auth_manager, "profile_dir", lambda _p: prof)
    auth_manager.clear_browser_session("xbox_wishlist")
    assert not prof.exists()


def test_start_browser_auth_rejects_overlapping_provider_session(profile_env, monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def slow_run(_provider, _session):
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
