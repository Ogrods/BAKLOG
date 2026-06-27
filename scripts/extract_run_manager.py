"""One-off: extract Run + RunManager from server.py into shared/run_manager.py."""
from __future__ import annotations

import re
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
src = (ROOT / "server.py").read_text(encoding="utf-8").splitlines()
block = "\n".join(src[820:2357])

header = textwrap.dedent(
    '''
    """Run queue: Run + RunManager (extracted from server.py)."""

    from __future__ import annotations

    import json
    import os
    import queue
    import subprocess
    import threading
    import time
    import uuid
    from collections import deque
    from pathlib import Path
    from typing import Any

    from shared.install_paths import data_root, get_active_profile_id
    from shared.install_paths import runs_dir as profile_runs_dir
    from shared.log_redact import redact_log_line as _redact_log_line
    from shared.subprocess_guard import (
        pid_alive as _pid_alive,
        popen_fetcher,
        terminate_pid as _terminate_pid,
    )

    MAX_HISTORY = 200
    MAX_LINES_PER_RUN = 25_000
    STALL_FIRST_NOTICE_SEC = 60
    STALL_REPEAT_SEC = 60
    STALL_POLL_SEC = 1.0
    SILENT_STALL_KILL_SEC = 180
    TERMINATE_GRACE_SEC = 5
    CANCEL_STUCK_GRACE_SEC = TERMINATE_GRACE_SEC + 2
    WATCHDOG_INTERVAL_SEC = 3.0
    LAUNCH_TIMEOUT_SEC = 30
    STUCK_NO_PROC_GRACE_SEC = LAUNCH_TIMEOUT_SEC + 15
    _IN_FLIGHT_STATUSES = frozenset({"queued", "launching", "running", "cancelling"})
    _runs_file_lock = threading.Lock()


    def _server():
        import server as mod
        return mod


    def _fetchers() -> dict[str, dict[str, Any]]:
        return _server().FETCHERS


    def _internal_jobs() -> dict[str, dict[str, Any]]:
        return _server().INTERNAL_JOBS


    def _max_run_seconds_for_key(key: str) -> float:
        return _server()._max_run_seconds_for_key(key)


    def _active_runs_path() -> Path:
        return profile_runs_dir() / "active.json"


    def _queue_path() -> Path:
        return profile_runs_dir() / "queue.json"


    def _run_history_path() -> Path:
        return profile_runs_dir() / "history.json"

    '''
).lstrip("\n")

text = block
text = text.replace("_read_json_file(ACTIVE_RUNS_FILE", "_read_json_file(_active_runs_path()")
text = text.replace("_write_json_atomic(ACTIVE_RUNS_FILE", "_write_json_atomic(_active_runs_path()")
text = text.replace("_read_json_file(QUEUE_FILE", "_read_json_file(_queue_path()")
text = text.replace("_write_json_atomic(QUEUE_FILE", "_write_json_atomic(_queue_path()")
text = text.replace("path or RUN_HISTORY_FILE", "path or _run_history_path()")
text = text.replace(
    "def _load_run_history() -> list[dict[str, Any]]:\n"
    "    return _load_run_history_from(RUN_HISTORY_FILE)",
    "def _load_run_history() -> list[dict[str, Any]]:\n"
    "    return _load_run_history_from(_run_history_path())",
)
text = text.replace(
    "def _save_run_history(entries: list[dict[str, Any]]) -> None:\n"
    "    _save_run_history_to(RUN_HISTORY_FILE, entries)",
    "def _save_run_history(entries: list[dict[str, Any]]) -> None:\n"
    "    _save_run_history_to(_run_history_path(), entries)",
)
text = text.replace("runs_dir: Path = RUNS_DIR,", "runs_dir_path: Path | None = None,")
text = text.replace(
    "        self._runs_dir = runs_dir\n        self._runs_dir.mkdir",
    "        self._runs_dir = runs_dir_path if runs_dir_path is not None else profile_runs_dir()\n"
    "        self._runs_dir.mkdir",
)
text = text.replace(
    "        self._runs_dir = runs_dir or RUNS_DIR",
    "        self._runs_dir = runs_dir if runs_dir is not None else profile_runs_dir()",
)
text = text.replace("runs_dir(profile_id=profile_id)", "profile_runs_dir(profile_id=profile_id)")
text = text.replace("runs_dir(profile_id=pid)", "profile_runs_dir(profile_id=pid)")
text = text.replace("hist_file = runs_dir(profile_id=profile_id)", "hist_file = profile_runs_dir(profile_id=profile_id)")
text = text.replace("self._runs_dir = runs_dir()", "self._runs_dir = profile_runs_dir()")
text = re.sub(r"\bFETCHERS\b", "_fetchers()", text)
text = re.sub(r"\bINTERNAL_JOBS\b", "_internal_jobs()", text)
text = text.replace("_fetchers()()", "_fetchers()")
text = text.replace("_internal_jobs()()", "_internal_jobs()")

out = header + text
(ROOT / "shared" / "run_manager.py").write_text(out, encoding="utf-8")
print(f"wrote {len(out.splitlines())} lines to shared/run_manager.py")
