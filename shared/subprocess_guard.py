"""Subprocess containment helpers (Windows job objects, child-PID snapshots)."""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Any


def _max_run_seconds_from_env(default: float = 1800.0) -> float:
    raw = os.environ.get("BAKLOG_MAX_RUN_SECONDS", "").strip()
    if not raw:
        return default
    try:
        return max(60.0, float(raw))
    except ValueError:
        return default


def _win_child_pids_snapshot(ppid: int) -> set[int]:
    """Enumerate child PIDs via the Toolhelp snapshot API (no subprocess spawn).

    This is called on every test by the leak-detection fixture, so it must be
    cheap — shelling out to PowerShell here added ~1s per test (minutes across
    the suite). ``CreateToolhelp32Snapshot`` returns in well under a millisecond.
    """
    import ctypes
    from ctypes import wintypes

    TH32CS_SNAPPROCESS = 0x00000002

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_char * 260),
        ]

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.Process32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32)]
    kernel32.Process32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    invalid = wintypes.HANDLE(-1).value
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == invalid:
        return set()
    try:
        entry = PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
        pids: set[int] = set()
        if not kernel32.Process32First(snap, ctypes.byref(entry)):
            return set()
        while True:
            if int(entry.th32ParentProcessID) == ppid:
                pids.add(int(entry.th32ProcessID))
            if not kernel32.Process32Next(snap, ctypes.byref(entry)):
                break
        return pids
    finally:
        kernel32.CloseHandle(snap)


def child_pids_of(parent_pid: int | None = None) -> set[int]:
    """Return PIDs whose parent is ``parent_pid`` (defaults to current process)."""
    ppid = parent_pid if parent_pid is not None else os.getpid()
    if sys.platform == "win32":
        try:
            return _win_child_pids_snapshot(ppid)
        except OSError:
            return set()
    try:
        out = subprocess.check_output(
            ["ps", "-o", "pid=", "--ppid", str(ppid)],
            stderr=subprocess.DEVNULL,
            timeout=5,
            text=True,
        )
        return {int(x) for x in out.split() if x.strip().isdigit()}
    except (OSError, subprocess.SubprocessError, ValueError):
        return set()


def terminate_pid_tree(pid: int) -> None:
    """Kill a process and its descendants."""
    if pid <= 0:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    else:
        import signal

        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass


class _WindowsJobPopen(subprocess.Popen[str]):
    """Popen that assigns the child to a job object killed when the job handle closes."""

    _job_handle: int | None = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        if sys.platform == "win32":
            kwargs.setdefault(
                "creationflags",
                kwargs.get("creationflags", 0)
                | getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        super().__init__(*args, **kwargs)
        if sys.platform == "win32" and self.pid:
            self._assign_job()

    def _assign_job(self) -> None:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
        JobObjectExtendedLimitInformation = 9

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
            job,
            JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
        ):
            kernel32.CloseHandle(job)
            return
        handle = getattr(self, "_handle", None)
        if handle is None:
            kernel32.CloseHandle(job)
            return
        if not kernel32.AssignProcessToJobObject(job, handle):
            kernel32.CloseHandle(job)
            return
        self._job_handle = job


def popen_fetcher(*args: Any, **kwargs: Any) -> subprocess.Popen[str]:
    """Launch a fetcher subprocess with platform-appropriate tree containment."""
    if sys.platform == "win32":
        return _WindowsJobPopen(*args, **kwargs)
    return subprocess.Popen(*args, **kwargs)
