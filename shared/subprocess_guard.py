from __future__ import annotations
import os
import subprocess
import sys
from typing import Any

def _max_run_seconds_from_env(default: float=1800.0) -> float:
    raw = os.environ.get('BAKLOG_MAX_RUN_SECONDS', '').strip()
    if not raw:
        return default
    try:
        return max(60.0, float(raw))
    except ValueError:
        return default

def _win_proc_table() -> dict[int, int]:
    import ctypes
    from ctypes import wintypes
    TH32CS_SNAPPROCESS = 2

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD), ('th32ProcessID', wintypes.DWORD), ('th32DefaultHeapID', ctypes.POINTER(ctypes.c_ulong)), ('th32ModuleID', wintypes.DWORD), ('cntThreads', wintypes.DWORD), ('th32ParentProcessID', wintypes.DWORD), ('pcPriClassBase', ctypes.c_long), ('dwFlags', wintypes.DWORD), ('szExeFile', ctypes.c_char * 260)]
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.Process32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32)]
    kernel32.Process32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    invalid = wintypes.HANDLE(-1).value
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == invalid:
        return {}
    try:
        entry = PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
        table: dict[int, int] = {}
        if not kernel32.Process32First(snap, ctypes.byref(entry)):
            return {}
        while True:
            table[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            if not kernel32.Process32Next(snap, ctypes.byref(entry)):
                break
        return table
    finally:
        kernel32.CloseHandle(snap)

def _win_child_pids_snapshot(ppid: int) -> set[int]:
    return {pid for pid, parent in _win_proc_table().items() if parent == ppid}

def _proc_parent_map() -> dict[int, int]:
    if sys.platform == 'win32':
        try:
            return _win_proc_table()
        except (OSError, AttributeError):
            return {}
    try:
        out = subprocess.check_output(['ps', '-eo', 'pid=,ppid='], stderr=subprocess.DEVNULL, timeout=5, text=True)
    except (OSError, subprocess.SubprocessError):
        return {}
    table: dict[int, int] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            table[int(parts[0])] = int(parts[1])
    return table

def child_pids_of(parent_pid: int | None=None) -> set[int]:
    ppid = parent_pid if parent_pid is not None else os.getpid()
    if sys.platform == 'win32':
        try:
            return _win_child_pids_snapshot(ppid)
        except OSError:
            return set()
        except AttributeError:
            pass
    try:
        out = subprocess.check_output(['ps', '-o', 'pid=', '--ppid', str(ppid)], stderr=subprocess.DEVNULL, timeout=5, text=True)
        return {int(x) for x in out.split() if x.strip().isdigit()}
    except (OSError, subprocess.SubprocessError, ValueError):
        return set()

def related_pids(pid: int) -> set[int]:
    if pid <= 0:
        return set()
    table = _proc_parent_map()
    related = {pid}
    cur = pid
    while cur in table:
        parent = table[cur]
        if parent <= 0 or parent in related:
            break
        related.add(parent)
        cur = parent
    children_by_parent: dict[int, list[int]] = {}
    for child, parent in table.items():
        children_by_parent.setdefault(parent, []).append(child)
    stack = [pid]
    while stack:
        node = stack.pop()
        for child in children_by_parent.get(node, ()):
            if child not in related:
                related.add(child)
                stack.append(child)
    return related

def terminate_pid_tree(pid: int) -> None:
    if pid <= 0:
        return
    if sys.platform == 'win32':
        subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], capture_output=True, check=False, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    else:
        import signal
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass

class _WindowsJobPopen(subprocess.Popen[str]):
    _job_handle: int | None = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        if sys.platform == 'win32':
            kwargs.setdefault('creationflags', kwargs.get('creationflags', 0) | getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        super().__init__(*args, **kwargs)
        if sys.platform == 'win32' and self.pid:
            self._assign_job()

    def _assign_job(self) -> None:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.windll.kernel32
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 8192
        JobObjectExtendedLimitInformation = 9

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [('PerProcessUserTimeLimit', ctypes.c_longlong), ('PerJobUserTimeLimit', ctypes.c_longlong), ('LimitFlags', wintypes.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t), ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', wintypes.DWORD), ('Affinity', ctypes.c_size_t), ('PriorityClass', wintypes.DWORD), ('SchedulingClass', wintypes.DWORD)]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [('ReadOperationCount', ctypes.c_ulonglong), ('WriteOperationCount', ctypes.c_ulonglong), ('OtherOperationCount', ctypes.c_ulonglong), ('ReadTransferCount', ctypes.c_ulonglong), ('WriteTransferCount', ctypes.c_ulonglong), ('OtherTransferCount', ctypes.c_ulonglong)]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [('BasicLimitInformation', JOBOBJECT_BASIC_LIMIT_INFORMATION), ('IoInfo', IO_COUNTERS), ('ProcessMemoryLimit', ctypes.c_size_t), ('JobMemoryLimit', ctypes.c_size_t), ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(job, JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info)):
            kernel32.CloseHandle(job)
            return
        handle = getattr(self, '_handle', None)
        if handle is None:
            kernel32.CloseHandle(job)
            return
        if not kernel32.AssignProcessToJobObject(job, handle):
            kernel32.CloseHandle(job)
            return
        self._job_handle = job

def popen_fetcher(*args: Any, **kwargs: Any) -> subprocess.Popen[str]:
    if sys.platform == 'win32':
        return _WindowsJobPopen(*args, **kwargs)
    return subprocess.Popen(*args, **kwargs)