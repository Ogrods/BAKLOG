"""Dev server refuses a second bind when the port is already in use."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import server


def test_baklog_dev_server_disallows_reuse() -> None:
    assert server.BaklogDevServer.allow_reuse_address is False


def test_dev_server_port_busy_when_connect_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        server.socket,
        "create_connection",
        lambda *_a, **_k: MagicMock(__enter__=lambda s: s, __exit__=lambda *a: None),
    )
    assert server._dev_server_port_busy() is True


def test_dev_server_port_busy_when_connect_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _refuse(*_a, **_k):
        raise ConnectionRefusedError

    monkeypatch.setattr(server.socket, "create_connection", _refuse)
    assert server._dev_server_port_busy() is False


def test_exit_if_dev_server_busy_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "_dev_server_port_busy", lambda: True)
    monkeypatch.setattr(server, "_reclaim_stale_server", lambda: False)
    with pytest.raises(SystemExit) as exc:
        server._exit_if_dev_server_busy()
    assert exc.value.code == 1


def test_exit_if_dev_server_busy_reclaims_orphan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"reclaim": 0, "busy": 0}

    def _busy() -> bool:
        calls["busy"] += 1
        return calls["busy"] == 1

    monkeypatch.setattr(server, "_dev_server_port_busy", _busy)
    monkeypatch.setattr(
        server,
        "_reclaim_stale_server",
        lambda: calls.__setitem__("reclaim", calls["reclaim"] + 1) or True,
    )
    server._exit_if_dev_server_busy()
    assert calls["reclaim"] == 1
    assert calls["busy"] == 2


def test_pid_alive_windows_uses_tasklist_not_signal_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server.sys, "platform", "win32")

    def _kill_raises(*_a, **_k):
        raise OSError(87, "The parameter is incorrect")

    monkeypatch.setattr(server.os, "kill", _kill_raises)
    monkeypatch.setattr(
        server.subprocess,
        "run",
        lambda *a, **k: type("R", (), {"stdout": '"python.exe","1234","Console","5","1 K"\n'})(),
    )
    assert server._pid_alive(1234) is True
