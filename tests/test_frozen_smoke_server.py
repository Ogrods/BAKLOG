"""Unit tests for scripts/frozen_smoke_server.py (no real server spawned)."""

from __future__ import annotations

from pathlib import Path

import pytest

import scripts.frozen_smoke_server as smoke_server


class _FakeProc:
    def __init__(self, pid: int = 4242, *, returncode: int | None = None) -> None:
        self.pid = pid
        self._returncode = returncode
        self.stderr = None

    def poll(self) -> int | None:
        return self._returncode


@pytest.fixture
def stub_exe(tmp_path: Path) -> Path:
    exe = tmp_path / "BAKLOG"
    exe.write_text("", encoding="utf-8")
    return exe


def _patch_lifecycle(
    monkeypatch,
    *,
    proc,
    port_free=(True, None),
    listener=None,
    reachable=True,
):
    """Stub the spawn/probe/kill seams so no real process or socket is used."""
    killed: list[int] = []
    monkeypatch.setattr(smoke_server, "ensure_port_free", lambda **kw: port_free)
    monkeypatch.setattr(smoke_server, "port_listener_pid", lambda host, port: listener)
    monkeypatch.setattr(smoke_server, "wait_for_port_free", lambda **kw: None)
    monkeypatch.setattr(smoke_server, "terminate_pid_tree", killed.append)
    monkeypatch.setattr(smoke_server, "_spawn", lambda exe, cwd, env: proc)
    monkeypatch.setattr(smoke_server, "_probe_config", lambda base, **kw: reachable)
    return killed


def test_server_ready_when_config_responds(monkeypatch, stub_exe: Path) -> None:
    proc = _FakeProc()
    killed = _patch_lifecycle(monkeypatch, proc=proc)

    with smoke_server.FrozenSmokeServer(stub_exe, port=8799) as server:
        assert server.ok is True
        assert server.error is None
        assert server.base == "http://127.0.0.1:8799"
    assert killed == [proc.pid]


def test_server_injects_port_into_env(monkeypatch, stub_exe: Path) -> None:
    _patch_lifecycle(monkeypatch, proc=_FakeProc())

    with smoke_server.FrozenSmokeServer(stub_exe, env={"A": "b"}, port=8766) as server:
        assert server.env["PORT"] == "8766"
        assert server.env["A"] == "b"


def test_server_reports_early_exit(monkeypatch, stub_exe: Path) -> None:
    _patch_lifecycle(monkeypatch, proc=_FakeProc(returncode=3), reachable=False)

    with smoke_server.FrozenSmokeServer(stub_exe, port=8799) as server:
        assert server.ok is False
        assert "exited with code 3" in (server.error or "")


def test_server_reports_timeout(monkeypatch, stub_exe: Path) -> None:
    _patch_lifecycle(monkeypatch, proc=_FakeProc(), reachable=False)
    monkeypatch.setattr(smoke_server.time, "sleep", lambda _: None)

    server = smoke_server.FrozenSmokeServer(stub_exe, port=8799, start_timeout_sec=0.01)
    with server:
        assert server.ok is False
        assert "did not respond" in (server.error or "")


def test_server_reports_blocked_port(monkeypatch, stub_exe: Path) -> None:
    _patch_lifecycle(monkeypatch, proc=_FakeProc(), port_free=(False, "port busy"))

    with smoke_server.FrozenSmokeServer(stub_exe, port=8799) as server:
        assert server.ok is False
        assert server.error == "port busy"
        assert server.proc is None


def test_server_missing_exe(tmp_path: Path) -> None:
    with smoke_server.FrozenSmokeServer(tmp_path / "nope", port=8799) as server:
        assert server.ok is False
        assert "not found" in (server.error or "")


def test_exit_kills_leftover_port_holder(monkeypatch, stub_exe: Path) -> None:
    proc = _FakeProc(pid=111, returncode=0)
    killed = _patch_lifecycle(monkeypatch, proc=proc, listener=222)

    with smoke_server.FrozenSmokeServer(stub_exe, port=8799) as server:
        assert server.ok is True
    # Parent already exited; the process still holding the port is killed.
    assert killed == [222]
