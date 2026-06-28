"""Server boot wiring for the background scheduler."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scheduler
import server


def test_start_background_scheduler_starts_thread(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(server, "SCHEDULER", None, raising=False)
    monkeypatch.setattr(scheduler, "BackgroundScheduler", lambda **kwargs: fake)
    server._start_background_scheduler()
    fake.start.assert_called_once()
    assert server.SCHEDULER is fake


def test_start_background_scheduler_survives_import_error(monkeypatch):
    monkeypatch.setattr(server, "SCHEDULER", None, raising=False)

    def _boom(**kwargs):
        raise RuntimeError("scheduler unavailable")

    monkeypatch.setattr(scheduler, "BackgroundScheduler", _boom)
    server._start_background_scheduler()  # must not raise
    assert server.SCHEDULER is None
