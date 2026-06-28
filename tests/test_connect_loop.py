"""Unit tests for auth.connect_loop.run_connect_poll."""

from __future__ import annotations

import pytest

from auth.connect_loop import run_connect_poll


class _FakeTime:
    def __init__(self, step_s: float = 1.0) -> None:
        self.t = 0.0
        self.step_s = step_s

    def time(self) -> float:
        self.t += self.step_s
        return self.t


class _FakePage:
    def wait_for_timeout(self, _ms: int) -> None:
        return None


class _FakeContext:
    def __init__(self) -> None:
        self.pages = [_FakePage()]


def test_run_connect_poll_returns_when_check_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _FakeTime(step_s=1.0)
    monkeypatch.setattr("auth.connect_loop.time", clock)
    monkeypatch.setattr("auth.connect_loop.abort_if_browser_closed", lambda _ctx: None)

    calls = {"n": 0}

    def check() -> dict[str, str] | None:
        calls["n"] += 1
        if calls["n"] >= 2:
            return {"TOKEN": "ok"}
        return None

    creds = run_connect_poll(
        context=_FakeContext(),
        session=None,
        deadline=clock.time() + 60,
        poll_sec=0.1,
        check=check,
        timeout_message="timed out",
    )
    assert creds == {"TOKEN": "ok"}
    assert calls["n"] == 2


def test_run_connect_poll_raises_on_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _FakeTime(step_s=5.0)
    monkeypatch.setattr("auth.connect_loop.time", clock)
    monkeypatch.setattr("auth.connect_loop.abort_if_browser_closed", lambda _ctx: None)

    with pytest.raises(RuntimeError, match="no session"):
        run_connect_poll(
            context=_FakeContext(),
            session=None,
            deadline=clock.time() + 10,
            poll_sec=0.1,
            check=lambda: None,
            timeout_message="no session",
        )
