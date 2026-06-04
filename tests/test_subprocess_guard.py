"""Tests for shared.subprocess_guard (Windows job-object containment)."""
from __future__ import annotations

import subprocess
import sys
import time

import pytest

from shared.subprocess_guard import _WindowsJobPopen, popen_fetcher, terminate_pid_tree


@pytest.mark.skipif(sys.platform != "win32", reason="Windows job object")
def test_popen_fetcher_uses_windows_job_popen() -> None:
    proc = popen_fetcher(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        assert isinstance(proc, _WindowsJobPopen)
        assert proc.poll() is None
    finally:
        terminate_pid_tree(proc.pid)
        proc.wait(timeout=5)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows job object")
def test_job_popen_child_terminated_on_close() -> None:
    proc = popen_fetcher(
        [sys.executable, "-c", "import time; time.sleep(120)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    pid = proc.pid
    proc.terminate()
    proc.wait(timeout=5)
    time.sleep(0.2)
    assert subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}"],
        capture_output=True,
        text=True,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    ).stdout.find(str(pid)) == -1
