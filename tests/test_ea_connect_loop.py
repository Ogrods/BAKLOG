"""Fake-CDP loop test: EA connect sniffs Bearer and probes before saving."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import auth.runner as runner


class _FakeTime:
    def __init__(self, step_s: float = 1.0) -> None:
        self.t = 0.0
        self.step_s = step_s

    def time(self) -> float:
        self.t += self.step_s
        return self.t


class _FakePage:
    url = "https://www.ea.com/sales/deals"
    is_closed = False

    def goto(self, *_a, **_k) -> None:
        pass

    def bring_to_front(self) -> None:
        pass

    def wait_for_timeout(self, _ms: int) -> None:
        pass


def test_extract_ea_uses_header_sniffer(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _FakeTime(step_s=5.0)
    monkeypatch.setattr(runner, "time", clock)
    monkeypatch.setattr("auth.connect_loop.time", clock)
    monkeypatch.setattr(runner, "abort_if_browser_closed", lambda _ctx: None)
    monkeypatch.setattr("clients.ea_session.probe_ea_token", lambda _t, _c: {"ok": True})

    handlers: list = []

    class Ctx:
        pages = [_FakePage()]

        def on(self, event: str, handler) -> None:
            if event == "request":
                handlers.append(handler)

        def cookies(self) -> list:
            return []

    ctx = Ctx()
    page = _FakePage()

    def _inject_token() -> None:
        for h in handlers:
            h(
                MagicMock(
                    url="https://service-aggregation-layer.juno.ea.com/graphql",
                    headers={"Authorization": "Bearer loop-token"},
                )
            )

    monkeypatch.setattr(_FakePage, "wait_for_timeout", lambda _self, _ms: _inject_token())

    creds = runner._extract_ea(page, ctx, session=None)
    assert creds == {"EA_PROFILE": "ready", "EA_BEARER_TOKEN": "loop-token"}
