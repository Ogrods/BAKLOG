"""Tests for EA Connections session validation."""
from __future__ import annotations

from unittest.mock import MagicMock

from auth.runner import _extract_ea


def test_extract_ea_returns_bearer_token(monkeypatch) -> None:
    monkeypatch.setattr("clients.ea_session.probe_ea_token", lambda _t, _c: {"ok": True})

    handlers: list = []

    class Ctx:
        def on(self, event: str, handler) -> None:
            if event == "request":
                handlers.append(handler)

        def cookies(self) -> list:
            return []

    class Page:
        url = "https://www.ea.com/sales/deals"

        def goto(self, *_a, **_k) -> None:
            pass

        def bring_to_front(self) -> None:
            pass

        def wait_for_timeout(self, _ms: int) -> None:
            for h in handlers:
                h(
                    MagicMock(
                        url="https://service-aggregation-layer.juno.ea.com/graphql",
                        headers={"Authorization": "Bearer connect-token"},
                    )
                )

    creds = _extract_ea(Page(), Ctx())
    assert creds["EA_PROFILE"] == "ready"
    assert creds["EA_BEARER_TOKEN"] == "connect-token"
