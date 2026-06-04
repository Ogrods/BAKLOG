"""Browser-auth worker must inherit the request profile context."""
from __future__ import annotations

import threading
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
