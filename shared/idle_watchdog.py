"""Idle self-exit watchdog for the local BAKLOG dev server.

A daemon thread that triggers a graceful shutdown after a no-activity window so
abandoned dev servers (terminal closed, browser tab gone) stop piling up across
agent sessions. A server with an open dashboard tab is polled every ~30s, so it
never idles out; an agent-launched server with no browser self-exits.

Lives in ``shared/`` (not ``server.py``) to keep the server module under its CI
line cap and to stay import-cycle free: the server passes in its own
``is_idle_ok`` probe and ``on_idle`` shutdown callback.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

DEFAULT_CHECK_INTERVAL_S = 60.0

_lock = threading.Lock()
_last_activity = time.monotonic()


def note_activity() -> None:
    """Record that a client just contacted the server (called per request)."""
    global _last_activity
    with _lock:
        _last_activity = time.monotonic()


def seconds_since_activity() -> float:
    """Seconds elapsed since the last :func:`note_activity` call."""
    with _lock:
        return time.monotonic() - _last_activity


def start_idle_watchdog(
    timeout_s: float,
    is_idle_ok: Callable[[], bool],
    on_idle: Callable[[], None],
    *,
    check_interval_s: float = DEFAULT_CHECK_INTERVAL_S,
) -> threading.Thread | None:
    """Start a daemon thread that calls ``on_idle()`` once the server has been
    idle for ``timeout_s`` seconds AND ``is_idle_ok()`` returns True.

    Returns ``None`` when disabled (``timeout_s <= 0``). The thread fires
    ``on_idle`` at most once, then exits. A falsy ``is_idle_ok`` probe (e.g. an
    in-flight fetch or an active sign-in) resets the countdown instead of
    exiting, so long-running work is never interrupted.
    """
    if timeout_s <= 0:
        return None

    note_activity()  # reset baseline so the countdown starts now

    def _loop() -> None:
        interval = max(1.0, min(check_interval_s, timeout_s))
        while True:
            time.sleep(interval)
            if seconds_since_activity() < timeout_s:
                continue
            try:
                if not is_idle_ok():
                    note_activity()  # something is busy; restart the countdown
                    continue
            except Exception:  # noqa: BLE001 - a probe error must not kill the loop
                note_activity()
                continue
            try:
                on_idle()
            except Exception:  # noqa: BLE001 - best-effort graceful shutdown
                pass
            return

    thread = threading.Thread(
        target=_loop, name="baklog-idle-watchdog", daemon=True
    )
    thread.start()
    return thread
