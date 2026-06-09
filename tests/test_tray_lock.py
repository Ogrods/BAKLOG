"""Tests for tray single-instance lock (shared/tray_lock.py)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import shared.tray_lock as tray_lock


@pytest.fixture(autouse=True)
def _reset_lock():
    tray_lock.release_tray_lock()
    yield
    tray_lock.release_tray_lock()


def test_acquire_and_release_round_trip(monkeypatch, tmp_path):
    if sys.platform == "win32":
        assert tray_lock.acquire_tray_lock() is True
        assert tray_lock.acquire_tray_lock() is True  # same process re-entrant ok
        tray_lock.release_tray_lock()
        assert tray_lock.acquire_tray_lock() is True
        return
    monkeypatch.setattr("shared.install_paths.data_root", lambda: tmp_path)
    assert tray_lock.acquire_tray_lock() is True
    tray_lock.release_tray_lock()
    assert tray_lock.acquire_tray_lock() is True


def test_second_holder_blocked_on_posix(monkeypatch, tmp_path):
    if sys.platform == "win32":
        pytest.skip("Windows mutex test needs a second process")
    monkeypatch.setattr("shared.install_paths.data_root", lambda: tmp_path)
    assert tray_lock.acquire_tray_lock() is True
    # Simulate another process holding the lock file.
    lock_path = tmp_path / ".tray.lock"
    other = lock_path.open("w", encoding="utf-8")
    import fcntl

    fcntl.flock(other.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        assert tray_lock.acquire_tray_lock() is False
    finally:
        fcntl.flock(other.fileno(), fcntl.LOCK_UN)
        other.close()
