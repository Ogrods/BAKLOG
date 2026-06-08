"""stop_baklog cleanup helper: pid selection, dry-run, and force-kill paths."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from shared import dev_server_pids

ROOT = Path(__file__).resolve().parents[1]


def _load_stop_baklog():
    spec = importlib.util.spec_from_file_location(
        "stop_baklog", ROOT / "scripts" / "stop_baklog.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


stop_baklog = _load_stop_baklog()


# ---- shared pid selection -------------------------------------------------


def test_pid_listening_on_port_parses_netstat(monkeypatch: pytest.MonkeyPatch) -> None:
    sample = "\n".join(
        [
            "  TCP    127.0.0.1:8765    0.0.0.0:0    LISTENING    12345",
            "  TCP    127.0.0.1:8765    127.0.0.1:51000    ESTABLISHED    999",
            "  TCP    127.0.0.1:9999    0.0.0.0:0    LISTENING    777",
        ]
    )
    monkeypatch.setattr(dev_server_pids.sys, "platform", "win32")
    monkeypatch.setattr(
        dev_server_pids.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(stdout=sample),
    )
    assert dev_server_pids.pid_listening_on_port("127.0.0.1", 8765) == 12345


def test_pid_listening_on_port_none_when_no_listener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dev_server_pids.sys, "platform", "win32")
    monkeypatch.setattr(
        dev_server_pids.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(stdout="  TCP  127.0.0.1:1234  0.0.0.0:0  LISTENING  5"),
    )
    assert dev_server_pids.pid_listening_on_port("127.0.0.1", 8765) is None


# ---- target collection ----------------------------------------------------


def test_collect_targets_unions_and_sorts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stop_baklog, "_port_pids", lambda: {200, 100})
    monkeypatch.setattr(stop_baklog, "_cmdline_pids", lambda: {100, 300})
    assert stop_baklog.collect_targets() == [100, 200, 300]


# ---- dry-run --------------------------------------------------------------


def test_dry_run_lists_without_killing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    killed: list[int] = []
    monkeypatch.setattr(stop_baklog, "collect_targets", lambda: [111, 222])
    monkeypatch.setattr(stop_baklog, "_port_open", lambda: True)
    monkeypatch.setattr(
        stop_baklog, "terminate_pid_tree", lambda pid: killed.append(pid)
    )
    monkeypatch.setattr(stop_baklog.sys, "argv", ["stop_baklog.py", "--dry-run"])

    assert stop_baklog.main() == 0
    out = capsys.readouterr().out
    assert "would stop pids: 111, 222" in out
    assert killed == []  # dry-run never kills


# ---- force path -----------------------------------------------------------


def test_force_kills_targets_and_clears_pid_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    killed: list[int] = []
    pid_file = tmp_path / ".baklog_server.pid"
    pid_file.write_text("4242", encoding="utf-8")

    monkeypatch.setattr(stop_baklog, "_request_graceful_shutdown", lambda: False)
    monkeypatch.setattr(stop_baklog, "collect_targets", lambda: [4242, 5252])
    monkeypatch.setattr(
        stop_baklog, "terminate_pid_tree", lambda pid: killed.append(pid)
    )
    monkeypatch.setattr(stop_baklog, "PID_FILE", pid_file)
    monkeypatch.setattr(stop_baklog.sys, "argv", ["stop_baklog.py"])

    assert stop_baklog.main() == 0
    out = capsys.readouterr().out
    assert killed == [4242, 5252]
    assert "force-stopped pids: 4242, 5252" in out
    assert not pid_file.is_file()  # stale pid file removed
