from unittest.mock import MagicMock

import pytest

from shared import dev_server_pids as dsp


def test_port_busy_true_when_connect_succeeds(monkeypatch):
    monkeypatch.setattr(
        dsp.socket, "create_connection", lambda *_a, **_k: MagicMock(__enter__=lambda s: s, __exit__=lambda *a: None)
    )
    assert dsp.port_busy("127.0.0.1", 8765) is True


def test_port_busy_false_when_connect_refused(monkeypatch):

    def _refuse(*_a, **_k):
        raise ConnectionRefusedError

    monkeypatch.setattr(dsp.socket, "create_connection", _refuse)
    assert dsp.port_busy("127.0.0.1", 8765) is False


def test_clear_stale_pid_file_removes_dead_pid(monkeypatch, tmp_path):
    pid_file = tmp_path / ".baklog_server.pid"
    pid_file.write_text("99999", encoding="utf-8")
    monkeypatch.setattr(dsp, "pid_is_python_server", lambda _pid: False)
    assert dsp.clear_stale_pid_file(pid_file) is True
    assert not pid_file.is_file()


def test_clear_stale_pid_file_keeps_live_server(monkeypatch, tmp_path):
    pid_file = tmp_path / ".baklog_server.pid"
    pid_file.write_text("4242", encoding="utf-8")
    monkeypatch.setattr(dsp, "pid_is_python_server", lambda _pid: True)
    assert dsp.clear_stale_pid_file(pid_file) is False
    assert pid_file.is_file()


def test_clear_stale_pid_file_missing_file_is_noop(tmp_path):
    assert dsp.clear_stale_pid_file(tmp_path / "absent.pid") is False


def test_reclaim_stale_server_kills_orphan_from_pid_file(monkeypatch, tmp_path):
    pid_file = tmp_path / ".baklog_server.pid"
    pid_file.write_text("4242", encoding="utf-8")
    killed = []
    monkeypatch.setattr(dsp, "pid_is_python_server", lambda _pid: True)
    monkeypatch.setattr(dsp, "terminate_pid", lambda pid: killed.append(pid))
    assert dsp.reclaim_stale_server("127.0.0.1", 8765, pid_file) is True
    assert killed == [4242]


def test_reclaim_stale_server_skips_non_server_pid(monkeypatch, tmp_path):
    pid_file = tmp_path / ".baklog_server.pid"
    pid_file.write_text("4242", encoding="utf-8")
    monkeypatch.setattr(dsp, "pid_is_python_server", lambda _pid: False)
    monkeypatch.setattr(dsp, "pid_listening_on_port", lambda *a, **k: None)
    monkeypatch.setattr(dsp, "terminate_pid", lambda _pid: pytest.fail("should not kill"))
    assert dsp.reclaim_stale_server("127.0.0.1", 8765, pid_file) is False


def test_reclaim_or_exit_returns_when_port_free(monkeypatch, tmp_path):
    monkeypatch.setattr(dsp, "clear_stale_pid_file", lambda _f: False)
    monkeypatch.setattr(dsp, "port_busy", lambda *a, **k: False)
    dsp.reclaim_or_exit("127.0.0.1", 8765, tmp_path / "pid", "busy")


def test_reclaim_or_exit_exits_when_busy_and_no_reclaim(monkeypatch, tmp_path):
    monkeypatch.setattr(dsp, "clear_stale_pid_file", lambda _f: False)
    monkeypatch.setattr(dsp, "port_busy", lambda *a, **k: True)
    monkeypatch.setattr(dsp, "reclaim_stale_server", lambda *a, **k: False)
    with pytest.raises(SystemExit) as exc:
        dsp.reclaim_or_exit("127.0.0.1", 8765, tmp_path / "pid", "busy")
    assert exc.value.code == 1


def test_reclaim_or_exit_reclaims_then_returns(monkeypatch, tmp_path):
    calls = {"busy": 0}

    def _busy(*_a, **_k):
        calls["busy"] += 1
        return calls["busy"] == 1

    monkeypatch.setattr(dsp, "clear_stale_pid_file", lambda _f: False)
    monkeypatch.setattr(dsp, "port_busy", _busy)
    monkeypatch.setattr(dsp, "reclaim_stale_server", lambda *a, **k: True)
    dsp.reclaim_or_exit("127.0.0.1", 8765, tmp_path / "pid", "busy")
    assert calls["busy"] == 2
