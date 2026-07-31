"""Battle.net headed-connect session detection (in-page probe + cookie fallback)."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from auth.connect_extractors import (
    _battlenet_probe_via_page,
    extract_battlenet_session,
)


class _FakePage:
    def __init__(self, result: Any) -> None:
        self._result = result
        self.evaluate_calls = 0

    def evaluate(self, _expr: str, *, timeout: float = 60) -> Any:
        self.evaluate_calls += 1
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class _FakeContext:
    def __init__(self, cookies: list[dict]) -> None:
        self._cookies = cookies

    def cookies(self) -> list[dict]:
        return list(self._cookies)


SESSION_COOKIES = [
    {"name": "XSRF-TOKEN", "value": "tok%3D%3D", "domain": ".battle.net"},
    {"name": "BA-tassession", "value": "sess", "domain": "account.battle.net"},
]


def test_probe_via_page_true_on_200() -> None:
    page = _FakePage({"ok": True, "status": 200})
    assert _battlenet_probe_via_page(page, xsrf="tok==") is True
    assert page.evaluate_calls == 1


def test_probe_via_page_false_on_401() -> None:
    page = _FakePage({"ok": False, "status": 401})
    assert _battlenet_probe_via_page(page) is False


def test_probe_via_page_false_on_evaluate_error() -> None:
    page = _FakePage(RuntimeError("cdp dead"))
    assert _battlenet_probe_via_page(page) is False


def test_extract_prefers_in_page_probe() -> None:
    ctx = _FakeContext(SESSION_COOKIES)
    page = _FakePage({"ok": True, "status": 200})
    with patch("clients.battlenet_client.probe_session") as probe:
        creds = extract_battlenet_session(ctx, page)
        probe.assert_not_called()
    assert creds is not None
    assert "BA-tassession=sess" in creds["BATTLENET_COOKIE"]
    assert "XSRF-TOKEN=tok%3D%3D" in creds["BATTLENET_COOKIE"]


def test_extract_falls_back_to_external_probe_when_page_fails() -> None:
    ctx = _FakeContext(SESSION_COOKIES)
    page = _FakePage({"ok": False, "status": 401})
    with patch(
        "clients.battlenet_client.probe_session",
        return_value={"modernGames": []},
    ) as probe:
        creds = extract_battlenet_session(ctx, page)
        probe.assert_called_once()
    assert creds is not None
    assert "BATTLENET_COOKIE" in creds


def test_extract_returns_none_when_external_probe_rejects() -> None:
    from clients.battlenet_client import BattleNetAuthError

    ctx = _FakeContext(SESSION_COOKIES)
    page = _FakePage({"ok": False, "status": 401})
    with patch(
        "clients.battlenet_client.probe_session",
        side_effect=BattleNetAuthError("401"),
    ):
        assert extract_battlenet_session(ctx, page) is None


def test_extract_without_page_uses_external_probe() -> None:
    ctx = _FakeContext(SESSION_COOKIES)
    with patch(
        "clients.battlenet_client.probe_session",
        return_value={"modernGames": []},
    ) as probe:
        creds = extract_battlenet_session(ctx)
        probe.assert_called_once()
    assert creds is not None


def test_extract_in_page_ok_but_empty_cookies_waits() -> None:
    ctx = _FakeContext([])
    page = _FakePage({"ok": True, "status": 200})
    with patch("clients.battlenet_client.probe_session") as probe:
        assert extract_battlenet_session(ctx, page) is None
        probe.assert_not_called()
