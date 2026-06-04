"""Tests for EA session sniff, probe, and login detection."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ea_client import EaAuthError, EaCaptureError
from ea_session import (
    DEFAULT_TRIGGER_URLS,
    is_ea_login_page,
    normalize_bearer,
    probe_ea_token,
    sniff_ea_bearer,
)


def test_normalize_bearer_strips_prefix() -> None:
    assert normalize_bearer("Bearer abc.def") == "abc.def"
    assert normalize_bearer("abc") == "abc"
    assert normalize_bearer("") is None


def test_is_ea_login_page_detects_signin_url() -> None:
    assert is_ea_login_page("", "https://signin.ea.com/p/juno/login")
    assert not is_ea_login_page("<html>deals</html>", "https://www.ea.com/sales/deals")


def test_probe_ea_token_ok(monkeypatch) -> None:
    class Client:
        def probe_owned_games(self) -> None:
            return None

    monkeypatch.setattr("ea_session.EaClient", lambda *_a, **_k: Client())
    out = probe_ea_token("tok")
    assert out["ok"] is True


def test_sniff_ea_bearer_from_request_handler() -> None:
    handlers: list = []

    class Ctx:
        def on(self, event: str, handler) -> None:
            if event == "request":
                handlers.append(handler)

        def cookies(self) -> list:
            return [{"name": "sid", "value": "1", "domain": ".ea.com"}]

    class Page:
        url = "https://www.ea.com/sales/deals"

        def goto(self, *_a, **_k) -> None:
            for h in handlers:
                h(
                    MagicMock(
                        url="https://service-aggregation-layer.juno.ea.com/graphql?x=1",
                        headers={"authorization": "Bearer sniffed-token"},
                    )
                )

        def wait_for_timeout(self, _ms: int) -> None:
            pass

        def content(self) -> str:
            return "<html>deals</html>"

    result = sniff_ea_bearer(Ctx(), Page(), trigger_urls=(DEFAULT_TRIGGER_URLS[0],), timeout_s=2)
    assert result.token == "sniffed-token"
    assert result.debug["token_captured"] is True


def test_sniff_login_page_raises_auth_error() -> None:
    class Ctx:
        def on(self, *_a, **_k) -> None:
            pass

        def cookies(self) -> list:
            return []

    class Page:
        url = "https://signin.ea.com/login"

        def goto(self, *_a, **_k) -> None:
            pass

        def wait_for_timeout(self, _ms: int) -> None:
            pass

        def content(self) -> str:
            return "<html>Sign in to your EA account</html>"

    with pytest.raises(EaAuthError, match="sign-in"):
        sniff_ea_bearer(Ctx(), Page(), trigger_urls=(DEFAULT_TRIGGER_URLS[0],), timeout_s=1)


def test_sniff_empty_non_login_raises_capture_error() -> None:
    class Ctx:
        def on(self, *_a, **_k) -> None:
            pass

        def cookies(self) -> list:
            return []

    class Page:
        url = "https://www.ea.com/sales/deals"

        def goto(self, *_a, **_k) -> None:
            pass

        def wait_for_timeout(self, _ms: int) -> None:
            pass

        def content(self) -> str:
            return "<html>deals loaded</html>"

    with pytest.raises(EaCaptureError, match="--headed"):
        sniff_ea_bearer(Ctx(), Page(), trigger_urls=(DEFAULT_TRIGGER_URLS[0],), timeout_s=1)
