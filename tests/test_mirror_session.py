"""Mirror bearer session note/clear for background uploads."""

from __future__ import annotations

import time

import pytest

from shared import entitlement, mirror_session


@pytest.fixture(autouse=True)
def _clear_session() -> None:
    mirror_session.clear_mirror_session()
    entitlement.clear_authenticated_plan_cache()
    yield
    mirror_session.clear_mirror_session()
    entitlement.clear_authenticated_plan_cache()


def test_note_and_get_mirror_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shared.supabase_auth.auth_enabled", lambda: True)
    monkeypatch.setattr(
        "shared.supabase_auth.verify_bearer_user",
        lambda *_a, **_k: {"id": "user-1", "email": "a@b.c"},
    )
    mirror_session.note_authenticated_mirror_session("Bearer tok-abc", user_id="user-1")
    got = mirror_session.get_mirror_session()
    assert got == ("user-1", "tok-abc")


def test_clear_background_auth_caches_drops_mirror_session() -> None:
    mirror_session._LAST_MIRROR_SESSION = (time.time(), "user-1", "tok-abc")
    assert mirror_session.get_mirror_session() is not None
    entitlement.clear_background_auth_caches()
    assert mirror_session.get_mirror_session() is None


def test_clear_mirror_session_direct() -> None:
    mirror_session._LAST_MIRROR_SESSION = (time.time(), "user-1", "tok")
    assert mirror_session.get_mirror_session() is not None
    mirror_session.clear_mirror_session()
    assert mirror_session.get_mirror_session() is None
