from __future__ import annotations
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import pytest
from shared import dev_server_pids
ROOT = Path(__file__).resolve().parents[1]

def _load_stop_baklog():
    spec = importlib.util.spec_from_file_location('stop_baklog', ROOT / 'scripts' / 'stop_baklog.py')
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
stop_baklog = _load_stop_baklog()

def test_pid_listening_on_port_parses_netstat(monkeypatch: pytest.MonkeyPatch) -> None:
    sample = '\n'.join(['  TCP    127.0.0.1:8765    0.0.0.0:0    LISTENING    12345', '  TCP    127.0.0.1:8765    127.0.0.1:51000    ESTABLISHED    999', '  TCP    127.0.0.1:9999    0.0.0.0:0    LISTENING    777'])
    monkeypatch.setattr(dev_server_pids.sys, 'platform', 'win32')
    monkeypatch.setattr(dev_server_pids.subprocess, 'run', lambda *a, **k: SimpleNamespace(stdout=sample))
    assert dev_server_pids.pid_listening_on_port('127.0.0.1', 8765) == 12345

def test_pid_listening_on_port_none_when_no_listener(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dev_server_pids.sys, 'platform', 'win32')
    monkeypatch.setattr(dev_server_pids.subprocess, 'run', lambda *a, **k: SimpleNamespace(stdout='  TCP  127.0.0.1:1234  0.0.0.0:0  LISTENING  5'))
    assert dev_server_pids.pid_listening_on_port('127.0.0.1', 8765) is None

def test_collect_targets_unions_and_sorts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stop_baklog, '_port_pids', lambda: {200, 100})
    monkeypatch.setattr(stop_baklog, '_cmdline_pids', lambda: {100, 300})
    assert stop_baklog.collect_targets() == [100, 200, 300]

def test_dry_run_lists_without_killing(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    killed: list[int] = []
    monkeypatch.setattr(stop_baklog, 'collect_targets', lambda: [111, 222])
    monkeypatch.setattr(stop_baklog, '_port_open', lambda: True)
    monkeypatch.setattr(stop_baklog, 'terminate_pid_tree', lambda pid: killed.append(pid))
    monkeypatch.setattr(stop_baklog.sys, 'argv', ['stop_baklog.py', '--dry-run'])
    assert stop_baklog.main() == 0
    out = capsys.readouterr().out
    assert 'would stop pids: 111, 222' in out
    assert killed == []

def test_force_kills_targets_and_clears_pid_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    killed: list[int] = []
    pid_file = tmp_path / '.baklog_server.pid'
    pid_file.write_text('4242', encoding='utf-8')
    monkeypatch.setattr(stop_baklog, '_request_graceful_shutdown', lambda: False)
    monkeypatch.setattr(stop_baklog, 'collect_targets', lambda: [4242, 5252])
    monkeypatch.setattr(stop_baklog, 'terminate_pid_tree', lambda pid: killed.append(pid))
    monkeypatch.setattr(stop_baklog, 'PID_FILE', pid_file)
    monkeypatch.setattr(stop_baklog.sys, 'argv', ['stop_baklog.py'])
    assert stop_baklog.main() == 0
    out = capsys.readouterr().out
    assert killed == [4242, 5252]
    assert 'force-stopped pids: 4242, 5252' in out
    assert not pid_file.is_file()

def test_dedupe_keeps_live_server_and_kills_extras(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    killed: list[int] = []
    pid_file = tmp_path / '.baklog_server.pid'
    pid_file.write_text('100', encoding='utf-8')
    monkeypatch.setattr(stop_baklog, '_live_server_pid', lambda: 100)
    monkeypatch.setattr(stop_baklog, 'collect_targets', lambda: [100, 200, 300])
    monkeypatch.setattr(stop_baklog, 'terminate_pid_tree', lambda pid: killed.append(pid))
    monkeypatch.setattr(stop_baklog, 'PID_FILE', pid_file)
    assert stop_baklog.dedupe() == 0
    out = capsys.readouterr().out
    assert killed == [200, 300]
    assert 'deduped stray pids: 200, 300' in out
    assert pid_file.is_file()

def test_dedupe_clears_pid_file_not_matching_keeper(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    killed: list[int] = []
    pid_file = tmp_path / '.baklog_server.pid'
    pid_file.write_text('999', encoding='utf-8')
    monkeypatch.setattr(stop_baklog, '_live_server_pid', lambda: 100)
    monkeypatch.setattr(stop_baklog, 'collect_targets', lambda: [100, 200])
    monkeypatch.setattr(stop_baklog, 'terminate_pid_tree', lambda pid: killed.append(pid))
    monkeypatch.setattr(stop_baklog, 'PID_FILE', pid_file)
    assert stop_baklog.dedupe() == 0
    assert killed == [200]
    assert not pid_file.is_file()

def test_dedupe_with_no_live_server_kills_all(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    killed: list[int] = []
    pid_file = tmp_path / '.baklog_server.pid'
    pid_file.write_text('200', encoding='utf-8')
    monkeypatch.setattr(stop_baklog, '_live_server_pid', lambda: None)
    monkeypatch.setattr(stop_baklog, 'collect_targets', lambda: [200, 300])
    monkeypatch.setattr(stop_baklog, 'terminate_pid_tree', lambda pid: killed.append(pid))
    monkeypatch.setattr(stop_baklog, 'PID_FILE', pid_file)
    assert stop_baklog.dedupe() == 0
    assert killed == [200, 300]
    assert not pid_file.is_file()

def test_dedupe_protects_keeper_launch_tree(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    killed: list[int] = []
    pid_file = tmp_path / '.baklog_server.pid'
    pid_file.write_text('7528', encoding='utf-8')
    monkeypatch.setattr(stop_baklog, '_live_server_pid', lambda: 7528)
    monkeypatch.setattr(stop_baklog, 'related_pids', lambda pid: {7528, 3208})
    monkeypatch.setattr(stop_baklog, 'collect_targets', lambda: [3208, 7528, 9999])
    monkeypatch.setattr(stop_baklog, 'terminate_pid_tree', lambda pid: killed.append(pid))
    monkeypatch.setattr(stop_baklog, 'PID_FILE', pid_file)
    assert stop_baklog.dedupe() == 0
    assert killed == [9999]
    assert pid_file.is_file()

def test_main_dedupe_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {'dedupe': 0}
    monkeypatch.setattr(stop_baklog, 'dedupe', lambda: called.__setitem__('dedupe', 1) or 0)
    monkeypatch.setattr(stop_baklog.sys, 'argv', ['stop_baklog.py', '--dedupe'])
    assert stop_baklog.main() == 0
    assert called['dedupe'] == 1