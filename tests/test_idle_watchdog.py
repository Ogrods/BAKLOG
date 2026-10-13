"""Idle self-exit watchdog in shared/idle_watchdog.py."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from unittest.mock import patch

import pytest

from shared import idle_watchdog


@pytest.fixture(autouse=True)
def _reset_activity() -> None:
    """Each test starts from a fresh activity baseline."""
    idle_watchdog.note_activity()


@pytest.fixture()
def start() -> Iterator[Callable[..., threading.Thread | None]]:
    """Start watchdogs that are stopped and joined on teardown.

    Busy/probe-error watchdogs never fire, so without a stop they outlive the
    test and spin on any later test's patched sleep.
    """
    stop = threading.Event()
    threads: list[threading.Thread] = []

    def _start(*args, **kwargs) -> threading.Thread | None:
        thread = idle_watchdog.start_idle_watchdog(*args, stop_event=stop, **kwargs)
        if thread is not None:
            threads.append(thread)
        return thread

    yield _start
    stop.set()
    for thread in threads:
        thread.join(timeout=2.0)
        assert not thread.is_alive(), "idle watchdog ignored stop_event"


def test_note_activity_resets_elapsed() -> None:
    idle_watchdog.note_activity()
    assert idle_watchdog.seconds_since_activity() < 0.5


def test_disabled_when_timeout_non_positive(start) -> None:
    fired = threading.Event()
    thread = start(0, lambda: True, fired.set, check_interval_s=0.01)
    assert thread is None
    assert not fired.is_set()


def test_fires_on_idle_when_ok(start) -> None:
    fired = threading.Event()
    thread = start(0.1, lambda: True, fired.set, check_interval_s=0.01)
    assert thread is not None
    # check_interval floors at 1s, so allow a couple of cycles.
    assert fired.wait(timeout=4.0), "watchdog never fired on idle"


def test_does_not_fire_while_busy(start) -> None:
    fired = threading.Event()
    # is_idle_ok always False -> countdown keeps resetting, on_idle never runs.
    start(0.1, lambda: False, fired.set, check_interval_s=0.01)
    assert not fired.wait(timeout=1.5), "watchdog fired while server was busy"


def test_probe_exception_does_not_fire(start) -> None:
    fired = threading.Event()

    def _raise() -> bool:
        raise RuntimeError("probe boom")

    start(0.1, _raise, fired.set, check_interval_s=0.01)
    assert not fired.wait(timeout=1.5), "watchdog fired despite probe error"


def test_stop_event_ends_thread_without_firing() -> None:
    fired = threading.Event()
    stop = threading.Event()
    thread = idle_watchdog.start_idle_watchdog(
        0.1, lambda: True, fired.set, check_interval_s=0.01, stop_event=stop
    )
    assert thread is not None
    stop.set()
    thread.join(timeout=2.0)
    assert not thread.is_alive()
    assert not fired.is_set()


def test_loop_does_not_call_patched_time_sleep(start) -> None:
    """Regression: a running watchdog spun on another test's patched time.sleep."""
    with patch("shared.idle_watchdog.time.sleep") as sleep:
        start(0.1, lambda: False, lambda: None, check_interval_s=0.01)
        # Let the 1s-floored loop complete at least one cycle under the patch.
        threading.Event().wait(1.3)
    sleep.assert_not_called()
