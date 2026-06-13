"""Idle self-exit watchdog in shared/idle_watchdog.py."""

from __future__ import annotations

import threading

import pytest

from shared import idle_watchdog


@pytest.fixture(autouse=True)
def _reset_activity() -> None:
    """Each test starts from a fresh activity baseline."""
    idle_watchdog.note_activity()


def test_note_activity_resets_elapsed() -> None:
    idle_watchdog.note_activity()
    assert idle_watchdog.seconds_since_activity() < 0.5


def test_disabled_when_timeout_non_positive() -> None:
    fired = threading.Event()
    thread = idle_watchdog.start_idle_watchdog(
        0, lambda: True, fired.set, check_interval_s=0.01
    )
    assert thread is None
    assert not fired.is_set()


def test_fires_on_idle_when_ok() -> None:
    fired = threading.Event()
    thread = idle_watchdog.start_idle_watchdog(
        0.1, lambda: True, fired.set, check_interval_s=0.01
    )
    assert thread is not None
    # check_interval floors at 1s, so allow a couple of cycles.
    assert fired.wait(timeout=4.0), "watchdog never fired on idle"


def test_does_not_fire_while_busy() -> None:
    fired = threading.Event()
    # is_idle_ok always False -> countdown keeps resetting, on_idle never runs.
    idle_watchdog.start_idle_watchdog(
        0.1, lambda: False, fired.set, check_interval_s=0.01
    )
    assert not fired.wait(timeout=1.5), "watchdog fired while server was busy"


def test_probe_exception_does_not_fire() -> None:
    fired = threading.Event()

    def _raise() -> bool:
        raise RuntimeError("probe boom")

    idle_watchdog.start_idle_watchdog(
        0.1, _raise, fired.set, check_interval_s=0.01
    )
    assert not fired.wait(timeout=1.5), "watchdog fired despite probe error"
