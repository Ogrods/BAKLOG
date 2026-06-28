from __future__ import annotations
import subprocess
import sys
import time
import pytest
import shared.subprocess_guard as subprocess_guard
from shared.subprocess_guard import _WindowsJobPopen, popen_fetcher, related_pids, terminate_pid_tree

def test_related_pids_includes_ancestors_and_descendants(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_table = {20476: 4, 3208: 20476, 7528: 3208, 8000: 7528, 50: 4, 51: 50, 52: 51}
    monkeypatch.setattr(subprocess_guard, '_proc_parent_map', lambda: fake_table)
    related = related_pids(7528)
    assert {7528, 3208, 20476} <= related
    assert 8000 in related
    assert related.isdisjoint({51, 52})

def test_related_pids_empty_for_nonpositive() -> None:
    assert related_pids(0) == set()
    assert related_pids(-1) == set()

@pytest.mark.skipif(sys.platform != 'win32', reason='Windows job object')
def test_popen_fetcher_uses_windows_job_popen() -> None:
    proc = popen_fetcher([sys.executable, '-c', 'import time; time.sleep(30)'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        assert isinstance(proc, _WindowsJobPopen)
        assert proc.poll() is None
    finally:
        terminate_pid_tree(proc.pid)
        proc.wait(timeout=5)

@pytest.mark.skipif(sys.platform != 'win32', reason='Windows job object')
def test_job_popen_child_terminated_on_close() -> None:
    proc = popen_fetcher([sys.executable, '-c', 'import time; time.sleep(120)'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    pid = proc.pid
    proc.terminate()
    proc.wait(timeout=5)
    time.sleep(0.2)
    assert subprocess.run(['tasklist', '/FI', f'PID eq {pid}'], capture_output=True, text=True, check=False, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout.find(str(pid)) == -1