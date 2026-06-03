"""Dev server refuses a second bind when the port is already in use."""

from __future__ import annotations

import socket
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
    with pytest.raises(SystemExit) as exc:
        server._exit_if_dev_server_busy()
    assert exc.value.code == 1
