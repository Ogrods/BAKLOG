import atexit
import sys

_LOCK_HANDLE = None


def release_tray_lock():
    global _LOCK_HANDLE
    handle = _LOCK_HANDLE
    _LOCK_HANDLE = None
    if handle is None:
        return
    try:
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.kernel32.CloseHandle(handle)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()
    except OSError:
        pass


def acquire_tray_lock():
    global _LOCK_HANDLE
    if _LOCK_HANDLE is not None:
        return True
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        CreateMutexW = kernel32.CreateMutexW
        CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        CreateMutexW.restype = wintypes.HANDLE
        handle = CreateMutexW(None, True, "Global\\BAKLOG.Tray.SingleInstance")
        if handle == 0:
            return True
        if ctypes.get_last_error() == 183:
            kernel32.CloseHandle(handle)
            return False
        _LOCK_HANDLE = handle
    else:
        import fcntl
        import os

        from shared.install_paths import data_root

        path = data_root() / ".tray.lock"
        path.parent.mkdir(parents=True, exist_ok=True)
        fh = path.open("w", encoding="utf-8")
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fh.close()
            return False
        fh.write(f"{os.getpid()}\n")
        fh.flush()
        _LOCK_HANDLE = fh
    atexit.register(release_tray_lock)
    return True
