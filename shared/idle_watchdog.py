from __future__ import annotations
import threading
import time
from collections.abc import Callable
DEFAULT_CHECK_INTERVAL_S = 60.0
_lock = threading.Lock()
_last_activity = time.monotonic()

def note_activity() -> None:
    global _last_activity
    with _lock:
        _last_activity = time.monotonic()

def seconds_since_activity() -> float:
    with _lock:
        return time.monotonic() - _last_activity

def start_idle_watchdog(timeout_s: float, is_idle_ok: Callable[[], bool], on_idle: Callable[[], None], *, check_interval_s: float=DEFAULT_CHECK_INTERVAL_S) -> threading.Thread | None:
    if timeout_s <= 0:
        return None
    note_activity()

    def _loop() -> None:
        interval = max(1.0, min(check_interval_s, timeout_s))
        while True:
            time.sleep(interval)
            if seconds_since_activity() < timeout_s:
                continue
            try:
                if not is_idle_ok():
                    note_activity()
                    continue
            except Exception:
                note_activity()
                continue
            try:
                on_idle()
            except Exception:
                pass
            return
    thread = threading.Thread(target=_loop, name='baklog-idle-watchdog', daemon=True)
    thread.start()
    return thread