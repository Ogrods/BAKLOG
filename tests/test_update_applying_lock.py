"""Applying lock coordinates tray watchdog with Install & restart."""

from __future__ import annotations

import json
import time
from pathlib import Path

from shared.update_ready_state import (
    APPLYING_LOCK_FILENAME,
    clear_apply_result,
    clear_applying_lock,
    is_update_apply_in_progress,
    write_applying_lock,
)


def test_write_and_clear_applying_lock(tmp_path: Path) -> None:
    assert is_update_apply_in_progress(tmp_path) is False
    write_applying_lock(tmp_path, version="0.8.37")
    lock = tmp_path / APPLYING_LOCK_FILENAME
    assert lock.is_file()
    data = json.loads(lock.read_text(encoding="utf-8"))
    assert data["version"] == "0.8.37"
    assert is_update_apply_in_progress(tmp_path) is True
    clear_applying_lock(tmp_path)
    assert is_update_apply_in_progress(tmp_path) is False


def test_stale_applying_lock_ignored(tmp_path: Path) -> None:
    write_applying_lock(tmp_path, version="0.8.37")
    lock = tmp_path / APPLYING_LOCK_FILENAME
    stale = time.time() - 3600
    # Touch mtime into the past beyond the default TTL.
    import os

    os.utime(lock, (stale, stale))
    assert is_update_apply_in_progress(tmp_path, max_age_sec=60) is False


def test_clear_apply_result_also_clears_lock(tmp_path: Path) -> None:
    write_applying_lock(tmp_path, version="0.8.37")
    (tmp_path / "apply-result.json").write_text('{"ok": true}', encoding="utf-8")
    clear_apply_result(tmp_path)
    assert not (tmp_path / APPLYING_LOCK_FILENAME).exists()
    assert not (tmp_path / "apply-result.json").exists()
