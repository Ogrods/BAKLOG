from __future__ import annotations
import pytest
import server

def test_baklog_dev_server_disallows_reuse() -> None:
    assert server.BaklogDevServer.allow_reuse_address is False

def test_pid_alive_windows_uses_tasklist_not_signal_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server.sys, 'platform', 'win32')

    def _kill_raises(*_a, **_k):
        raise OSError(87, 'The parameter is incorrect')
    monkeypatch.setattr(server.os, 'kill', _kill_raises)
    monkeypatch.setattr(server.subprocess, 'run', lambda *a, **k: type('R', (), {'stdout': '"python.exe","1234","Console","5","1 K"\n'})())
    assert server._pid_alive(1234) is True