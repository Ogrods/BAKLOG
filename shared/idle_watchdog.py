import threading
import time

DEFAULT_CHECK_INTERVAL_S = 60.0
_lock = threading.Lock()
_last_activity = time.monotonic()


def note_activity():
    global _last_activity
    with _lock:
        _last_activity = time.monotonic()


def seconds_since_activity():
    with _lock:
        return time.monotonic() - _last_activity


def start_idle_watchdog(timeout_s, is_idle_ok, on_idle, *, check_interval_s=DEFAULT_CHECK_INTERVAL_S):
    if timeout_s <= 0:
        return None
    note_activity()

    def _loop():
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

    thread = threading.Thread(target=_loop, name="baklog-idle-watchdog", daemon=True)
    thread.start()
    return thread
