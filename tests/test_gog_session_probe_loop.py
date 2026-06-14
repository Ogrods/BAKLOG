"""Regression guard for the GOG 'session expired even though it's still pulling' bug.

A user reported that right after a successful GOG fetch the connection chip
flipped to "session expired" while the fetch kept pulling. Root cause: the
session probe (auth.session_probe.probe_gog_session -> GogClient.validate_session)
hard-fails the moment ``embed.gog.com/userData.json`` returns 403, *before* the
owned-game-ID fallback that the actual fetch loop (fetch_gog.main) degrades to.
A transient 403 on userData.json (common when a probe races a running fetch)
therefore marks the session dead even though the fetcher still works via the
owned-ID path.

These tests drive the real GogClient.validate_session with a fake HTTP session,
so the probe behaviour is verified deterministically without network or a live
GOG login.
"""

from __future__ import annotations

import requests

from auth.session_probe import probe_gog_session
from gog_client import GogClient


class FakeResp:
    def __init__(self, status: int, payload: dict | None = None) -> None:
        self.status_code = status
        self._payload = payload or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self) -> dict:
        return self._payload


class FakeSession:
    """Routes embed.gog.com calls to configured status codes."""

    def __init__(self, *, userdata: int, library: int, owned: int) -> None:
        self.userdata = userdata
        self.library = library
        self.owned = owned
        self.hits: list[str] = []

    def get(self, url: str, **_k) -> FakeResp:
        self.hits.append(url)
        if "userData.json" in url:
            return FakeResp(self.userdata)
        if "getFilteredProducts" in url:
            return FakeResp(self.library, {"products": [], "totalPages": 1})
        if "/user/data/games" in url:
            return FakeResp(self.owned, {"owned": [1, 2, 3]})
        return FakeResp(404)


def _client(tmp_path, **statuses) -> GogClient:
    c = GogClient("fake-gog-al-token", cache_dir=tmp_path / "gogcache")
    c.session = FakeSession(**statuses)
    c._throttle = lambda: None  # no real 1s sleeps in tests
    return c


def test_userdata_403_but_owned_ids_work_keeps_session_alive(tmp_path) -> None:
    """userData.json 403 must NOT expire the session when owned-IDs still work.

    This is the exact 'expired while still pulling' case: the fetcher pulls fine
    via /user/data/games, so the probe must not declare the session dead.
    """
    client = _client(tmp_path, userdata=403, library=403, owned=200)
    assert client.validate_session() is True


def test_probe_gog_session_does_not_false_expire(tmp_path, monkeypatch) -> None:
    """probe_gog_session returns None (healthy) when the owned-ID path works."""
    client = _client(tmp_path, userdata=403, library=403, owned=200)
    monkeypatch.setattr("auth.session_probe.GogClient", lambda _token: client)
    assert probe_gog_session("fake-gog-al-token") is None


def test_genuinely_dead_session_still_fails(tmp_path) -> None:
    """When EVERY endpoint 403s, the session is really dead and must fail."""
    import pytest

    from gog_client import GogAuthError

    client = _client(tmp_path, userdata=403, library=403, owned=403)
    with pytest.raises(GogAuthError):
        client.validate_session()


def test_healthy_session_via_library(tmp_path) -> None:
    """The happy path (everything 200) still validates."""
    client = _client(tmp_path, userdata=200, library=200, owned=200)
    assert client.validate_session() is True


if __name__ == "__main__":
    import tempfile
    from pathlib import Path

    from gog_client import GogAuthError

    tmp = Path(tempfile.mkdtemp())
    c = _client(tmp, userdata=403, library=403, owned=200)
    try:
        result = c.validate_session()
        print(f"validate_session -> {result} (owned-IDs work; session kept alive)")
    except GogAuthError:
        print("validate_session -> RAISED GogAuthError (FALSE-EXPIRED: owned-IDs would have worked)")
