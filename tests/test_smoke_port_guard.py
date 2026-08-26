"""Unit tests for scripts/smoke_port_guard.py."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.smoke_port_guard as guard  # noqa: E402


class _FakeProc:
    def __init__(self, pid: int, *, returncode: int | None = None) -> None:
        self.pid = pid
        self._returncode = returncode

    def poll(self) -> int | None:
        return self._returncode


def test_proc_owns_dev_port_when_listener_in_tree(monkeypatch) -> None:
    proc = _FakeProc(1000)
    monkeypatch.setattr(guard, "port_listener_pid", lambda host, port: 2000)
    monkeypatch.setattr(guard, "related_pids", lambda pid: {1000, 2000} if pid == 1000 else set())
    assert guard.proc_owns_dev_port(proc) is True


def test_proc_owns_dev_port_false_on_collision(monkeypatch) -> None:
    proc = _FakeProc(1000)
    monkeypatch.setattr(guard, "port_listener_pid", lambda host, port: 4242)
    monkeypatch.setattr(guard, "related_pids", lambda pid: {1000} if pid == 1000 else set())
    assert guard.proc_owns_dev_port(proc) is False


def test_wait_for_owned_server_reports_collision(monkeypatch) -> None:
    proc = _FakeProc(1000)
    monkeypatch.setattr(guard, "port_listener_pid", lambda host, port: 4242)
    monkeypatch.setattr(guard, "related_pids", lambda pid: {1000} if pid == 1000 else set())
    ticks = iter([0.0, 0.0, 0.02])
    monkeypatch.setattr(guard.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(guard.time, "sleep", lambda _: None)

    ok, err = guard.wait_for_owned_server(proc, "http://127.0.0.1:8765", timeout_sec=0.01)
    assert ok is False
    assert err is not None
    assert "4242" in err
    assert "stop_baklog" in err


def test_port_collision_message() -> None:
    msg = guard.port_collision_message(99)
    assert "99" in msg
    assert "stop_baklog" in msg


def test_ensure_dev_port_free_when_idle(monkeypatch) -> None:
    monkeypatch.setattr(guard, "port_listener_pid", lambda host, port: None)
    ok, err = guard.ensure_dev_port_free(timeout_sec=0.01)
    assert ok is True
    assert err is None


def test_wait_for_http_server_ok(monkeypatch) -> None:
    proc = _FakeProc(1000)
    monkeypatch.setattr(guard.urllib.request, "urlopen", MagicMock(return_value=MagicMock(status=200, __enter__=lambda s: s, __exit__=lambda *a: None)))
    ok, err = guard.wait_for_http_server(proc, "http://127.0.0.1:8765", timeout_sec=0.01)
    assert ok is True
    assert err is None
