import re
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
src = (ROOT / "server.py").read_text(encoding="utf-8").splitlines()
block = "\n".join(src[820:2357])
header = textwrap.dedent(
    '\n    """Run queue: Run + RunManager (extracted from server.py)."""\n\n    from __future__ import annotations\n\n    import json\n    import os\n    import queue\n    import subprocess\n    import threading\n    import time\n    import uuid\n    from collections import deque\n    from pathlib import Path\n    from typing import Any\n\n    from shared.install_paths import data_root, get_active_profile_id\n    from shared.install_paths import runs_dir as profile_runs_dir\n    from shared.log_redact import redact_log_line as _redact_log_line\n    from shared.subprocess_guard import (\n        pid_alive as _pid_alive,\n        popen_fetcher,\n        terminate_pid as _terminate_pid,\n    )\n\n    MAX_HISTORY = 200\n    MAX_LINES_PER_RUN = 25_000\n    STALL_FIRST_NOTICE_SEC = 60\n    STALL_REPEAT_SEC = 60\n    STALL_POLL_SEC = 1.0\n    SILENT_STALL_KILL_SEC = 180\n    TERMINATE_GRACE_SEC = 5\n    CANCEL_STUCK_GRACE_SEC = TERMINATE_GRACE_SEC + 2\n    WATCHDOG_INTERVAL_SEC = 3.0\n    LAUNCH_TIMEOUT_SEC = 30\n    STUCK_NO_PROC_GRACE_SEC = LAUNCH_TIMEOUT_SEC + 15\n    _IN_FLIGHT_STATUSES = frozenset({"queued", "launching", "running", "cancelling"})\n    _runs_file_lock = threading.Lock()\n\n\n    def _server():\n        import server as mod\n        return mod\n\n\n    def _fetchers() -> dict[str, dict[str, Any]]:\n        return _server().FETCHERS\n\n\n    def _internal_jobs() -> dict[str, dict[str, Any]]:\n        return _server().INTERNAL_JOBS\n\n\n    def _max_run_seconds_for_key(key: str) -> float:\n        return _server()._max_run_seconds_for_key(key)\n\n\n    def _active_runs_path() -> Path:\n        return profile_runs_dir() / "active.json"\n\n\n    def _queue_path() -> Path:\n        return profile_runs_dir() / "queue.json"\n\n\n    def _run_history_path() -> Path:\n        return profile_runs_dir() / "history.json"\n\n    '
).lstrip("\n")
text = block
text = text.replace("_read_json_file(ACTIVE_RUNS_FILE", "_read_json_file(_active_runs_path()")
text = text.replace("_write_json_atomic(ACTIVE_RUNS_FILE", "_write_json_atomic(_active_runs_path()")
text = text.replace("_read_json_file(QUEUE_FILE", "_read_json_file(_queue_path()")
text = text.replace("_write_json_atomic(QUEUE_FILE", "_write_json_atomic(_queue_path()")
text = text.replace("path or RUN_HISTORY_FILE", "path or _run_history_path()")
text = text.replace(
    "def _load_run_history() -> list[dict[str, Any]]:\n    return _load_run_history_from(RUN_HISTORY_FILE)",
    "def _load_run_history() -> list[dict[str, Any]]:\n    return _load_run_history_from(_run_history_path())",
)
text = text.replace(
    "def _save_run_history(entries: list[dict[str, Any]]) -> None:\n    _save_run_history_to(RUN_HISTORY_FILE, entries)",
    "def _save_run_history(entries: list[dict[str, Any]]) -> None:\n    _save_run_history_to(_run_history_path(), entries)",
)
text = text.replace("runs_dir: Path = RUNS_DIR,", "runs_dir_path: Path | None = None,")
text = text.replace(
    "        self._runs_dir = runs_dir\n        self._runs_dir.mkdir",
    "        self._runs_dir = runs_dir_path if runs_dir_path is not None else profile_runs_dir()\n        self._runs_dir.mkdir",
)
text = text.replace(
    "        self._runs_dir = runs_dir or RUNS_DIR",
    "        self._runs_dir = runs_dir if runs_dir is not None else profile_runs_dir()",
)
text = text.replace("runs_dir(profile_id=profile_id)", "profile_runs_dir(profile_id=profile_id)")
text = text.replace("runs_dir(profile_id=pid)", "profile_runs_dir(profile_id=pid)")
text = text.replace(
    "hist_file = runs_dir(profile_id=profile_id)", "hist_file = profile_runs_dir(profile_id=profile_id)"
)
text = text.replace("self._runs_dir = runs_dir()", "self._runs_dir = profile_runs_dir()")
text = re.sub("\\bFETCHERS\\b", "_fetchers()", text)
text = re.sub("\\bINTERNAL_JOBS\\b", "_internal_jobs()", text)
text = text.replace("_fetchers()()", "_fetchers()")
text = text.replace("_internal_jobs()()", "_internal_jobs()")
out = header + text
(ROOT / "shared" / "run_manager.py").write_text(out, encoding="utf-8")
print(f"wrote {len(out.splitlines())} lines to shared/run_manager.py")
