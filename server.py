"""Local dev server for the BAKLOG dashboard.

Serves static files like ``python -m http.server`` and adds a tiny API that
lets dashboard chips trigger Python fetchers and stream their output back to
the browser via Server-Sent Events. Also owns the user's personal data
(statuses, notes, priorities, prefs, manually-added games) so it survives
browser changes, port changes, and cache wipes.

Endpoints:
    GET  /api/runs                 -> {active, queue, history}
    POST /api/run/<key>            -> {run_id, status}    (queues a fetcher)
    POST /api/run/<run_id>/cancel  -> cancel one queued or running fetcher
    POST /api/runs/cancel          -> cancel all in-flight fetchers (active + queue)
    GET  /api/stream/<run_id>      -> SSE: line / done / error events (?since=N or Last-Event-ID for resume)
    GET  /api/personal        -> {personal, prefs, manual, updated_at}
    PUT  /api/personal        -> overwrite the whole document atomically
    GET  /api/profiles        -> {active, active_label, legacy, profiles[]}
    POST /api/profiles        -> create profile {label}
    POST /api/profiles/active -> switch active profile {id}
    PUT  /api/profiles/<id>   -> rename profile {label}
    DELETE /api/profiles/<id> -> delete non-active profile
    GET  /api/auth/status     -> per-provider connection state
    POST /api/auth/<p>/start  -> begin CDP browser sign-in (returns session_id)
    GET  /api/auth/<id>/stream -> SSE auth flow events
    PUT  /api/auth/<p>/credentials -> save form API keys
    POST /api/auth/<p>/disconnect  -> wipe stored credentials
    POST /api/auth/<p>/enable     -> re-enable local-only provider (e.g. Amazon launcher)
    POST /api/auth/master-password -> set optional portable encryption passphrase
    POST /api/auth/secrets/export  -> download encrypted portable bundle
    POST /api/auth/secrets/import  -> restore bundle (?passphrase=...)
    GET  /oauth/epic/callback -> Epic OAuth redirect handler

Bind: 127.0.0.1 only. The fetcher whitelist is loaded from fetchers/manifest.json
so the browser cannot execute arbitrary commands.
"""
from __future__ import annotations

import atexit
import html
import json
import os
import queue
import re
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass

HOST = "127.0.0.1"
PORT = int(os.environ.get("PORT", "8765"))
_DEV_SERVER_BUSY_MSG = (
    f"BAKLOG dev server is already running on http://{HOST}:{PORT} — "
    "stop that instance first (it owns the port)."
)
MAX_HISTORY = 200
MAX_LINES_PER_RUN = 25_000
MAX_SSE_CONNECTIONS = 8
STALL_FIRST_NOTICE_SEC = 60
STALL_REPEAT_SEC = 60
STALL_POLL_SEC = 1.0
SILENT_STALL_KILL_SEC = 180  # if a fetcher emits zero lines AND proc still alive after this, force-kill
TERMINATE_GRACE_SEC = 5  # how long to wait after proc.terminate() before falling back to taskkill /F
CANCEL_STUCK_GRACE_SEC = TERMINATE_GRACE_SEC + 2
WATCHDOG_INTERVAL_SEC = 3.0
# Profile switch: wait for cancelled runs to finish (kill + re-kill window).
SWITCH_CANCEL_WAIT_SEC = 2 * TERMINATE_GRACE_SEC
LAUNCH_TIMEOUT_SEC = 30  # max wait for subprocess.Popen() to return before declaring the run failed.
# Grace before force-finalizing launching/running runs with no live subprocess (worker wedged).
STUCK_NO_PROC_GRACE_SEC = LAUNCH_TIMEOUT_SEC + 15
# On Windows the AppX/WindowsApps Python stub can deadlock inside CreateProcess
# when spawned from another AppX Python process — the worker thread blocks
# indefinitely with no zombie child to kill. The launch watchdog aborts the
# wait so subsequent queued runs can still execute.
_runs_file_lock = threading.Lock()

# Statuses that occupy a queue slot (cap = 2: one active + one queued).
_IN_FLIGHT_STATUSES = frozenset({"queued", "launching", "running", "cancelling"})

_sse_connections = 0
_sse_lock = threading.Lock()

_BAKLOG_LOCAL_HEADER = "X-BAKLOG-Local"
_BAKLOG_IMPORT_PASSPHRASE_HEADER = "X-BAKLOG-Import-Passphrase"
_LOCAL_HOSTNAMES = frozenset({"127.0.0.1", "localhost", "[::1]"})
# Epic OAuth state -> (expiry_monotonic, profile_id).
# Production Epic Connect uses Playwright + authorizationCode paste (auth/runner.py);
# this map is only populated if something calls _register_epic_oauth_state (legacy redirect flow).
_epic_oauth_states: dict[str, tuple[float, str]] = {}
_stream_tickets: dict[str, tuple[str, float]] = {}
_stream_tickets_lock = threading.Lock()
_STREAM_TICKET_TTL_SEC = 30.0
_LOG_REDACT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+", re.I), r"\1[redacted]"),
    (re.compile(r"(Cookie:\s*)([^\s]+)", re.I), r"\1[redacted]"),
    (re.compile(r"(api[_-]?key[\"']?\s*[:=]\s*)[\"']?[\w\-]+", re.I), r"\1[redacted]"),
    (re.compile(r"([?&]ticket=)[^&\s]+", re.I), r"\1[redacted]"),
]


def _redact_log_line(text: str) -> str:
    out = text
    for pattern, repl in _LOG_REDACT_PATTERNS:
        out = pattern.sub(repl, out)
    return out


def _register_epic_oauth_state(
    state: str,
    profile_id: str | None = None,
    *,
    ttl_sec: float = 600.0,
) -> None:
    from shared.profile_paths import get_active_profile_id

    pid = profile_id or get_active_profile_id()
    _epic_oauth_states[state] = (time.monotonic() + ttl_sec, pid)


def _consume_epic_oauth_state(state: str | None, *, require_state: bool = False) -> str | None:
    """Return bound profile_id when state is valid; None when rejected."""
    if not state:
        if require_state:
            return None
        from shared.profile_paths import get_active_profile_id

        return get_active_profile_id()
    entry = _epic_oauth_states.pop(state, None)
    if not entry:
        return None
    expires, profile_id = entry
    if expires < time.monotonic():
        return None
    return profile_id


def _prune_expired_stream_tickets() -> None:
    now = time.time()
    expired = [k for k, (_, exp) in _stream_tickets.items() if exp < now]
    for k in expired:
        _stream_tickets.pop(k, None)


def _mint_stream_ticket(profile_id: str) -> str:
    ticket = secrets.token_urlsafe(32)
    with _stream_tickets_lock:
        _prune_expired_stream_tickets()
        _stream_tickets[ticket] = (profile_id, time.time() + _STREAM_TICKET_TTL_SEC)
    return ticket


def _consume_stream_ticket(ticket: str | None) -> str | None:
    if not ticket:
        return None
    with _stream_tickets_lock:
        entry = _stream_tickets.pop(ticket, None)
    if not entry:
        return None
    profile_id, expiry = entry
    if expiry < time.time():
        return None
    return profile_id


def _stream_ticket_from_handler(handler: SimpleHTTPRequestHandler) -> str | None:
    parsed = urlparse(handler.path)
    raw = (parse_qs(parsed.query).get("ticket") or [None])[0]
    if raw is None:
        return None
    return str(raw).strip() or None


def _authorize_stream(handler: SimpleHTTPRequestHandler) -> bool:
    """EventSource cannot send Authorization — validate single-use ?ticket= instead."""
    from shared.supabase_auth import auth_enabled

    if not auth_enabled():
        return True
    profile_id = _consume_stream_ticket(_stream_ticket_from_handler(handler))
    if not profile_id:
        _send_auth_required(handler)
        return False
    set_request_profile_id(profile_id)
    return True

# Personal-data persistence (scoped to active profile via shared.profile_paths).
from shared.platform_support import platform_supported  # noqa: E402
from shared.profile_paths import (  # noqa: E402
    PROFILE_CACHE_JSON_FILES,
    cache_json_path,
    catalog_path,
    clear_request_profile_id,
    get_active_profile_id,
    personal_backup_dir,
    personal_dir,
    personal_path,
    profile_root,
    runs_dir,
    set_request_profile_id,
)
from shared.subprocess_guard import _max_run_seconds_from_env, popen_fetcher  # noqa: E402

MAX_RUN_SECONDS = _max_run_seconds_from_env()


def _release_server_profile_env() -> str | None:
    """Drop BAKLOG_PROFILE from the server's own env so the profile menu /
    profiles/index.json always owns the active profile. Per-run fetchers set
    their own BAKLOG_PROFILE via subprocess_env_for_profile(), so this does not
    affect fetch subprocesses; one-off CLI fetchers are separate processes."""
    return os.environ.pop("BAKLOG_PROFILE", "").strip() or None


_SERVER_ENV_PROFILE_OVERRIDE = _release_server_profile_env()

RUNS_DIR = runs_dir()
ACTIVE_RUNS_FILE = RUNS_DIR / "active.json"
RUN_HISTORY_FILE = RUNS_DIR / "history.json"
QUEUE_FILE = RUNS_DIR / "queue.json"

# Kept for tests that monkeypatch these names.
PERSONAL_DIR = personal_dir()
PERSONAL_FILE = personal_path()
PERSONAL_BACKUP_DIR = personal_backup_dir()


def _refresh_personal_paths() -> None:
    """Rebind module-level personal + run paths after profile switch (tests may patch)."""
    global PERSONAL_DIR, PERSONAL_FILE, PERSONAL_BACKUP_DIR
    global RUNS_DIR, ACTIVE_RUNS_FILE, RUN_HISTORY_FILE, QUEUE_FILE
    PERSONAL_DIR = personal_dir()
    PERSONAL_FILE = personal_path()
    PERSONAL_BACKUP_DIR = personal_backup_dir()
    RUNS_DIR = runs_dir()
    ACTIVE_RUNS_FILE = RUNS_DIR / "active.json"
    RUN_HISTORY_FILE = RUNS_DIR / "history.json"
    QUEUE_FILE = RUNS_DIR / "queue.json"
    MANAGER.rebind_profile_paths()
PERSONAL_BACKUP_KEEP = 10
PERSONAL_MAX_BYTES = 32 * 1024 * 1024  # 32 MB hard cap on the PUT body
_personal_lock = threading.RLock()
_personal_last_backup_at = 0.0


def _empty_personal_doc() -> dict[str, Any]:
    return {
        "personal": {},
        "prefs": {},
        "manual": [],
        "libraryFirstSeen": {},
        "updated_at": None,
        "schema_version": 1,
    }


class PersonalCorruptError(RuntimeError):
    """personal.json is unreadable and no backup could be restored."""


def _normalize_personal_doc(doc: dict[str, Any]) -> dict[str, Any]:
    doc.setdefault("personal", {})
    doc.setdefault("prefs", {})
    doc.setdefault("manual", [])
    doc.setdefault("libraryFirstSeen", {})
    doc.setdefault("updated_at", None)
    doc.setdefault("schema_version", 1)
    return doc


def _restore_personal_from_backup() -> dict[str, Any] | None:
    backup_dir = personal_backup_dir()
    if not backup_dir.is_dir():
        return None
    backups = sorted(backup_dir.glob("personal-*.json"), reverse=True)
    for backup in backups:
        try:
            with backup.open("r", encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(doc, dict):
            return _normalize_personal_doc(doc)
    return None


def _load_personal_doc() -> dict[str, Any]:
    with _personal_lock:
        path = personal_path()
        if not path.exists():
            return _empty_personal_doc()
        try:
            with path.open("r", encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            restored = _restore_personal_from_backup()
            if restored is not None:
                print(
                    f"[personal] primary file corrupt ({exc!r}); serving newest backup",
                    file=sys.stderr,
                    flush=True,
                )
                return restored
            raise PersonalCorruptError(
                f"personal data at {path} is corrupt and no backup could be read"
            ) from exc
        if not isinstance(doc, dict):
            raise PersonalCorruptError(f"personal data at {path} is not a JSON object")
        return _normalize_personal_doc(doc)


def _validate_personal_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    personal = payload.get("personal", {})
    prefs = payload.get("prefs", {})
    manual = payload.get("manual", [])
    library_first_seen = payload.get("libraryFirstSeen", {})
    if not isinstance(personal, dict):
        raise ValueError("personal must be an object")
    if not isinstance(prefs, dict):
        raise ValueError("prefs must be an object")
    if not isinstance(manual, list):
        raise ValueError("manual must be an array")
    if not isinstance(library_first_seen, dict):
        raise ValueError("libraryFirstSeen must be an object")
    return {
        "personal": personal,
        "prefs": prefs,
        "manual": manual,
        "libraryFirstSeen": library_first_seen,
    }


def _rotate_personal_backup() -> None:
    """Keep a rolling set of timestamped backups so a bad save can't wipe
    out months of edits. Runs at most once every 5 minutes; the previous
    on-disk file becomes the backup before being overwritten."""
    global _personal_last_backup_at
    now = time.time()
    if now - _personal_last_backup_at < 300:
        return
    path = personal_path()
    if not path.exists():
        return
    backup_dir = personal_backup_dir()
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
    backup = backup_dir / f"personal-{stamp}.json"
    try:
        backup.write_bytes(path.read_bytes())
    except OSError as exc:
        print(f"[personal] backup failed: {exc!r}", file=sys.stderr)
        return
    _personal_last_backup_at = now
    # Prune oldest backups beyond the keep-count.
    backups = sorted(backup_dir.glob("personal-*.json"))
    for old in backups[:-PERSONAL_BACKUP_KEEP]:
        try:
            old.unlink()
        except OSError:
            pass


def _save_personal_doc(payload: dict[str, Any]) -> dict[str, Any]:
    """Atomic write: temp file + os.replace(). Never partial; never corrupted."""
    with _personal_lock:
        validated = _validate_personal_payload(payload)
        doc = _empty_personal_doc()
        doc.update(validated)
        doc["updated_at"] = time.time()
        pdir = personal_dir()
        pdir.mkdir(parents=True, exist_ok=True)
        path = personal_path()
        _rotate_personal_backup()
        tmp = path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        _refresh_personal_paths()
        return doc


# A fetcher is just a label plus an argv. argv is fixed at definition time;
# nothing the browser sends affects which command runs.
def _argv(*parts: str) -> list[str]:
    return [_python_executable(), *parts]


def _python_executable() -> str:
    """Prefer the project's venv interpreter when present."""
    override = os.environ.get("BAKLOG_PYTHON", "").strip()
    if override:
        return override
    candidates = [
        ROOT / ".venv" / "Scripts" / "python.exe",  # Windows
        ROOT / ".venv" / "bin" / "python",          # POSIX
        ROOT / ".venv" / "bin" / "python3",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    exe = sys.executable
    if sys.platform != "win32":
        return exe
    # The Microsoft Store "python.exe" shim under WindowsApps can deadlock when
    # this server (also launched via the shim) spawns fetcher subprocesses.
    # Resolve the real interpreter via the py launcher when we detect that stub.
    exe_norm = exe.replace("\\", "/")
    if "WindowsApps/python.exe" in exe_norm or exe_norm.endswith("/WindowsApps/python"):
        try:
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            proc = subprocess.run(
                ["py", "-3.13", "-c", "import sys; print(sys.executable)"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
                creationflags=flags,
            )
            resolved = (proc.stdout or "").strip()
            if proc.returncode == 0 and resolved and Path(resolved).is_file():
                return resolved
        except (OSError, subprocess.TimeoutExpired):
            pass
    return exe


MANIFEST_FILE = ROOT / "fetchers" / "manifest.json"


def _load_fetchers() -> dict[str, dict[str, Any]]:
    """Build the fetcher registry from fetchers/manifest.json."""
    try:
        from fetchers.registry import MANIFEST_PATH, validate_manifest

        errs = validate_manifest(MANIFEST_PATH)
        for err in errs:
            print(f"[fetchers] manifest: {err}", file=sys.stderr)
        raw = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        entries = raw.get("fetchers", [])
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[fetchers] manifest load failed: {exc!r}", file=sys.stderr)
        entries = []
    fetchers: dict[str, dict[str, Any]] = {}
    for entry in entries:
        key = entry.get("key")
        script = entry.get("script")
        label = entry.get("label", key)
        if not key or not script:
            continue
        extra_args = entry.get("args") or []
        if not isinstance(extra_args, list):
            print(f"[fetchers] {key}: 'args' must be a list, ignoring", file=sys.stderr)
            extra_args = []
        requires = entry.get("requires") or []
        if not isinstance(requires, list):
            requires = []
        refresh_args = entry.get("refreshArgs") or []
        if not isinstance(refresh_args, list):
            refresh_args = []
        platforms = entry.get("platforms") or []
        if not isinstance(platforms, list):
            platforms = []
        fetchers[key] = {
            "label": label,
            # Absolute script path so the launch never depends on subprocess cwd.
            "argv": _argv(str(ROOT / script), *map(str, extra_args)),
            "refreshArgs": [str(a) for a in refresh_args],
            "metaKey": entry.get("metaKey", key),
            "group": entry.get("group", "library"),
            "color": entry.get("color"),
            "requires": requires,
            "platforms": [str(p) for p in platforms],
        }
    return fetchers


def _missing_requirements(requires: list[dict[str, Any]]) -> list[str]:
    missing: list[str] = []
    resolve = None
    try:
        from auth import resolve_env as resolve
    except ImportError:
        resolve = None
    for req in requires:
        if not isinstance(req, dict):
            continue
        env_name = (req.get("env") or "").strip()
        if not env_name:
            continue
        if resolve:
            val = resolve(env_name, allow_process_env=False)
        else:
            val = ""
        if not val:
            missing.append(env_name)
    return missing


FETCHERS: dict[str, dict[str, Any]] = _load_fetchers()


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _terminate_pid(pid: int) -> None:
    if pid <= 0:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass


def _kill_pids_async(pids: list[int]) -> None:
    """Kill subprocess trees on a daemon thread so HTTP cancel handlers return immediately."""
    unique = list(dict.fromkeys(p for p in pids if p > 0))
    if not unique:
        return

    def _work() -> None:
        for pid in unique:
            _terminate_pid(pid)

    threading.Thread(target=_work, name="run-kill", daemon=True).start()


def _read_json_file(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _read_active_runs() -> list[dict[str, Any]]:
    with _runs_file_lock:
        data = _read_json_file(ACTIVE_RUNS_FILE, {"runs": []})
    runs = data.get("runs") if isinstance(data, dict) else []
    return runs if isinstance(runs, list) else []


def _write_active_runs(runs: list[dict[str, Any]]) -> None:
    with _runs_file_lock:
        _write_json_atomic(ACTIVE_RUNS_FILE, {"runs": runs})


def _load_durable_queue() -> list[dict[str, Any]]:
    with _runs_file_lock:
        data = _read_json_file(QUEUE_FILE, {"runs": []})
    runs = data.get("runs") if isinstance(data, dict) else []
    return runs if isinstance(runs, list) else []


def _save_durable_queue(entries: list[dict[str, Any]]) -> None:
    with _runs_file_lock:
        _write_json_atomic(QUEUE_FILE, {"runs": entries})


def _load_run_history_from(path: Path | None = None) -> list[dict[str, Any]]:
    hist_path = path or RUN_HISTORY_FILE
    data = _read_json_file(hist_path, [])
    return data if isinstance(data, list) else []


def _load_run_history() -> list[dict[str, Any]]:
    return _load_run_history_from(RUN_HISTORY_FILE)


def _save_run_history_to(path: Path, entries: list[dict[str, Any]]) -> None:
    _write_json_atomic(path, entries[:MAX_HISTORY])


def _save_run_history(entries: list[dict[str, Any]]) -> None:
    _save_run_history_to(RUN_HISTORY_FILE, entries)


class Run:
    """A single queued/running/completed fetcher invocation."""

    __slots__ = (
        "id", "key", "label", "status", "started_at", "ended_at", "exit_code",
        "lines", "_lock", "_listeners", "_finished", "_proc", "cancelled", "refresh",
        "_log_path", "_runs_dir", "profile_id", "_cancelling_since", "_no_proc_since",
        "_history_note", "_next_seq", "_total_lines", "_finalized",
    )

    def __init__(
        self,
        key: str,
        refresh: bool = False,
        *,
        runs_dir: Path = RUNS_DIR,
        profile_id: str | None = None,
    ) -> None:
        spec = FETCHERS[key]
        self.id: str = uuid.uuid4().hex[:12]
        self.key: str = key
        self.profile_id: str = profile_id or get_active_profile_id()
        self.label: str = spec["label"]
        self.refresh: bool = refresh
        self.status: str = "queued"  # queued | launching | running | cancelling | done | failed | cancelled
        self.started_at: float | None = None
        self.ended_at: float | None = None
        self.exit_code: int | None = None
        self.cancelled: bool = False
        self._finalized: bool = False
        self._proc: subprocess.Popen[str] | None = None
        self._runs_dir = runs_dir
        self._runs_dir.mkdir(parents=True, exist_ok=True)
        self._log_path = self._runs_dir / f"{self.id}.jsonl"
        # Ring buffer for live listeners; full log is on disk for replay.
        self.lines: deque[dict[str, Any]] = deque(maxlen=MAX_LINES_PER_RUN)
        self._next_seq = 0
        self._total_lines = 0
        self._lock = threading.Lock()
        self._listeners: set[queue.Queue] = set()
        self._finished = threading.Event()
        self._cancelling_since: float | None = None
        self._no_proc_since: float | None = None
        self._history_note: str | None = None
        self._restore_seq_from_disk()

    def _restore_seq_from_disk(self) -> None:
        """Resume monotonic seq / line totals from an existing jsonl log."""
        if not self._log_path.exists():
            return
        max_seq = 0
        count = 0
        fallback = 0
        try:
            with self._log_path.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    count += 1
                    msg = json.loads(line)
                    seq = msg.get("seq")
                    if seq is None:
                        fallback += 1
                        seq = fallback
                    max_seq = max(max_seq, int(seq))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[runs] log scan failed {self.id}: {exc!r}", file=sys.stderr)
            return
        self._next_seq = max_seq
        self._total_lines = count

    def to_summary(self) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "id": self.id,
            "key": self.key,
            "label": self.label,
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "exit_code": self.exit_code,
            "line_count": self._total_lines,
        }
        if self.exit_code == 4:
            summary["failure_kind"] = "auth"
        if self._history_note:
            summary["note"] = self._history_note
        summary["profile_id"] = self.profile_id
        return summary

    def add_line(self, stream: str, text: str) -> None:
        with self._lock:
            self._next_seq += 1
            self._total_lines += 1
            seq = self._next_seq
            msg = {
                "seq": seq,
                "t": time.time(),
                "stream": stream,
                "text": _redact_log_line(text),
            }
            self.lines.append(msg)
            try:
                with self._log_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(msg, ensure_ascii=False) + "\n")
            except OSError as exc:
                print(f"[runs] log write failed {self.id}: {exc!r}", file=sys.stderr)
            for q in list(self._listeners):
                try:
                    q.put_nowait(("line", msg))
                except queue.Full:
                    # Drop slow listeners rather than block the worker thread.
                    self._listeners.discard(q)

    def broadcast(self, event: str, data: dict[str, Any]) -> None:
        with self._lock:
            for q in list(self._listeners):
                try:
                    q.put_nowait((event, data))
                except queue.Full:
                    self._listeners.discard(q)

    def replay_lines(self, since: int = 0) -> list[dict[str, Any]]:
        """Return log lines with seq > since (full log on disk; ring buffer fallback)."""
        since = max(0, int(since))

        def _with_seq(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
            out: list[dict[str, Any]] = []
            fallback = 0
            for msg in messages:
                seq = msg.get("seq")
                if seq is None:
                    fallback += 1
                    msg = {**msg, "seq": fallback}
                out.append(msg)
            return [m for m in out if int(m.get("seq", 0)) > since]

        if self._log_path.exists():
            replay: list[dict[str, Any]] = []
            try:
                with self._log_path.open(encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        replay.append(json.loads(line))
                return _with_seq(replay)
            except (OSError, json.JSONDecodeError) as exc:
                print(f"[runs] log read failed {self.id}: {exc!r}", file=sys.stderr)
        with self._lock:
            return _with_seq(list(self.lines))

    def attach_listener(self, since: int = 0) -> tuple[queue.Queue, list[dict[str, Any]], bool]:
        """Return (queue, replay-buffer, already-finished)."""
        q: queue.Queue = queue.Queue(maxsize=1024)
        with self._lock:
            replay = self.replay_lines(since)
            done = self._finished.is_set()
            if not done:
                self._listeners.add(q)
        return q, replay, done

    def detach_listener(self, q: queue.Queue) -> None:
        with self._lock:
            self._listeners.discard(q)

    def mark_finished(self) -> None:
        self._finished.set()

    def argv(self) -> list[str]:
        spec = FETCHERS[self.key]
        argv = list(spec["argv"])
        if self.refresh:
            for arg in spec.get("refreshArgs") or []:
                if arg not in argv:
                    argv.append(arg)
        return argv

    def cancel(self) -> tuple[bool, list[int]]:
        """Mark cancelled/cancelling. Returns (changed, pids_to_kill). Never kills inline.

        broadcast()/mark_finished() acquire self._lock, so all notifications are
        emitted AFTER releasing the lock here — Run._lock is a plain (non-reentrant)
        Lock and broadcasting under it deadlocks the calling (HTTP) thread.
        """
        proc = None
        notify_done = False
        notify_cancelling = False
        with self._lock:
            if self.status in ("done", "failed", "cancelled") or self._finished.is_set():
                return False, []
            if self.status == "queued":
                self.status = "cancelled"
                self.exit_code = -1
                self.ended_at = time.time()
                notify_done = True
            elif self.status in ("launching", "running"):
                self.cancelled = True
                proc = self._proc
                if proc is None or proc.poll() is not None:
                    self.status = "cancelled"
                    self.exit_code = -1
                    self.ended_at = time.time()
                    notify_done = True
                else:
                    self.status = "cancelling"
                    self._cancelling_since = time.monotonic()
                    notify_cancelling = True
            elif self.status == "cancelling":
                return False, []
            else:
                return False, []
        if notify_cancelling:
            self.broadcast("status", {"status": self.status, "started_at": self.started_at})
        if notify_done:
            self.add_line("stderr", "[server] cancelled before start")
            self.mark_finished()
            self.broadcast(
                "done",
                {
                    "status": self.status,
                    "exit_code": self.exit_code,
                    "started_at": self.started_at,
                    "ended_at": self.ended_at,
                },
            )
            return True, []
        pids: list[int] = []
        if proc is not None and proc.poll() is None and proc.pid:
            pids.append(proc.pid)
        return True, pids


class RunManager:
    """Single-worker queue. Fetchers may share locks (PSN session, etc.) so
    we deliberately serialize them rather than spawn in parallel."""

    def __init__(self, runs_dir: Path | None = None, *, enable_watchdog: bool = True) -> None:
        self._runs_dir = runs_dir or RUNS_DIR
        self._runs_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._queue: queue.Queue[Run] = queue.Queue()
        self._pending: list[Run] = []  # queued + active, in submission order
        self._history: deque[dict[str, Any]] = deque(
            _load_run_history_from(self._runs_dir / "history.json")[-MAX_HISTORY:],
            maxlen=MAX_HISTORY,
        )
        self._active: Run | None = None
        self._runs_by_id: dict[str, Run] = {}
        self._last_queue_kick_at = 0.0
        self._watchdog_stop = threading.Event()
        self._reap_orphan_processes()
        self._start_worker_thread()
        self._watchdog_thread: threading.Thread | None = None
        if enable_watchdog:
            self._watchdog_thread = threading.Thread(
                target=self._watchdog_loop, name="run-watchdog", daemon=True
            )
            self._watchdog_thread.start()
        self._restore_durable_queue()

    def _start_worker_thread(self) -> None:
        self._worker_thread = threading.Thread(
            target=self._worker_loop, name="run-worker", daemon=True
        )
        self._worker_thread.start()

    def _ensure_worker_thread(self) -> None:
        """Restart the queue worker if the daemon thread died (leaves runs stuck queued)."""
        if self._worker_thread.is_alive():
            return
        print("[runs] worker thread died — restarting", file=sys.stderr, flush=True)
        self._start_worker_thread()

    def _resync_stalled_queue(self) -> int:
        """Put pending queued runs back on the worker queue when nothing is active.

        This heals the wedge where runs sit in ``_pending`` with status ``queued``
        but were never handed to ``_queue.get()`` (typically after the worker thread
        exited while the queue was empty).
        """
        to_put: list[Run] = []
        with self._lock:
            if self._active is not None and self._active._finished.is_set():
                self._active = None
            if self._active is not None:
                return 0
            if self._queue.qsize() > 0:
                return 0
            for r in self._pending:
                if r.status == "queued" and not r._finished.is_set():
                    to_put.append(r)
        for r in to_put:
            self._queue.put(r)
        if to_put:
            keys = ", ".join(r.key for r in to_put)
            print(f"[runs] re-queued {len(to_put)} stalled run(s): {keys}", file=sys.stderr, flush=True)
        return len(to_put)

    def _kick_queue_if_stalled(self) -> None:
        self._ensure_worker_thread()
        self._resync_stalled_queue()

    def _kick_queue_if_stalled_throttled(self) -> None:
        now = time.monotonic()
        if now - self._last_queue_kick_at < 1.0:
            return
        self._last_queue_kick_at = now
        self._kick_queue_if_stalled()

    def _watchdog_loop(self) -> None:
        while not self._watchdog_stop.wait(WATCHDOG_INTERVAL_SEC):
            try:
                self._kick_queue_if_stalled()
                self._force_finalize_stuck_cancelling()
                self._force_finalize_orphaned_runs()
            except Exception as exc:  # noqa: BLE001
                print(f"[runs] watchdog error: {exc!r}", file=sys.stderr, flush=True)

    def _force_finalize_stuck_cancelling(self) -> None:
        now = time.monotonic()
        stuck: list[Run] = []
        with self._lock:
            for r in self._pending:
                if (
                    r.status == "cancelling"
                    and r._cancelling_since is not None
                    and now - r._cancelling_since > CANCEL_STUCK_GRACE_SEC
                ):
                    stuck.append(r)
            active = self._active
            if (
                active
                and active.status == "cancelling"
                and active._cancelling_since is not None
                and now - active._cancelling_since > CANCEL_STUCK_GRACE_SEC
                and active not in stuck
            ):
                stuck.append(active)
        for run in stuck:
            pids = self._collect_pids_for_run(run, [])
            if pids:
                _kill_pids_async(pids)
            with run._lock:
                if not run._finished.is_set():
                    run.status = "cancelled"
                    run.exit_code = -1
                    if run.ended_at is None:
                        run.ended_at = time.time()
            if not run._finished.is_set():
                run.mark_finished()
                run.broadcast(
                    "done",
                    {
                        "status": run.status,
                        "exit_code": run.exit_code,
                        "started_at": run.started_at,
                        "ended_at": run.ended_at,
                    },
                )
            self._finalize_run(run)

    def _run_has_live_process(self, run: Run) -> bool:
        if run._proc is not None and run._proc.poll() is None:
            return True
        for entry in _read_active_runs():
            if entry.get("id") == run.id:
                pid = int(entry.get("pid") or 0)
                if _pid_alive(pid):
                    return True
        return False

    def _force_finalize_orphaned_runs(self) -> None:
        """Force-finalize launching/running runs with no live subprocess."""
        now = time.monotonic()
        stuck: list[Run] = []
        with self._lock:
            candidates: list[Run] = []
            active = self._active
            if (
                active
                and active.status in ("launching", "running")
                and not active._finished.is_set()
            ):
                candidates.append(active)
            for r in self._pending:
                if (
                    r.status in ("launching", "running")
                    and not r._finished.is_set()
                    and r not in candidates
                ):
                    candidates.append(r)
            for run in candidates:
                if self._run_has_live_process(run):
                    run._no_proc_since = None
                    continue
                if run._no_proc_since is None:
                    run._no_proc_since = now
                    continue
                if now - run._no_proc_since > STUCK_NO_PROC_GRACE_SEC:
                    stuck.append(run)
        for run in stuck:
            pids = self._collect_pids_for_run(run, [])
            if pids:
                _kill_pids_async(pids)
            with run._lock:
                if not run._finished.is_set():
                    run.status = "failed"
                    run.exit_code = -1
                    if run.ended_at is None:
                        run.ended_at = time.time()
                    run._history_note = (
                        "force-finalized: no live subprocess (worker stalled)"
                    )
            if not run._finished.is_set():
                run.add_line(
                    "stderr",
                    "[server] no live subprocess — force-finalizing stalled run "
                    "so the queue can advance",
                )
                run.mark_finished()
                run.broadcast(
                    "done",
                    {
                        "status": run.status,
                        "exit_code": run.exit_code,
                        "started_at": run.started_at,
                        "ended_at": run.ended_at,
                    },
                )
            self._finalize_run(run)

    def _collect_pids_for_run(self, run: Run, proc_pids: list[int]) -> list[int]:
        pids = list(proc_pids)
        if run._proc is not None and run._proc.poll() is None and run._proc.pid:
            if run._proc.pid not in pids:
                pids.append(run._proc.pid)
        for entry in _read_active_runs():
            if entry.get("id") == run.id:
                pid = int(entry.get("pid") or 0)
                if pid > 0 and pid not in pids:
                    pids.append(pid)
        return pids

    def _complete_cancel_after_kill(self, run: Run) -> None:
        proc = run._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.wait(timeout=TERMINATE_GRACE_SEC)
            except Exception:  # noqa: BLE001
                pass
        # mark_finished()/broadcast() acquire run._lock themselves, so we must
        # NOT hold it here — Run._lock is a plain (non-reentrant) Lock.
        should_finish = False
        with run._lock:
            if not run._finished.is_set():
                run.status = "cancelled"
                run.exit_code = -1
                if run.ended_at is None:
                    run.ended_at = time.time()
                should_finish = True
        if should_finish:
            run.mark_finished()
            run.broadcast(
                "done",
                {
                    "status": run.status,
                    "exit_code": run.exit_code,
                    "started_at": run.started_at,
                    "ended_at": run.ended_at,
                },
            )
        self._finalize_run(run)

    def stream_terminal_summary(self, run_id: str) -> dict[str, Any] | None:
        """History summary for a run no longer in memory (SSE reconnect after finish)."""
        with self._lock:
            for h in self._history:
                if h.get("id") == run_id:
                    return h
        hist_file = self._runs_dir / "history.json"
        for h in _load_run_history_from(hist_file):
            if h.get("id") == run_id:
                return h
        return None

    def rebind_profile_paths(self) -> None:
        """Point run storage at the active profile after POST /api/profiles/active."""
        self._runs_dir = runs_dir()
        self._runs_dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._history = deque(
                _load_run_history_from(self._runs_dir / "history.json")[-MAX_HISTORY:],
                maxlen=MAX_HISTORY,
            )

    def _persist_queue(self) -> None:
        with self._lock:
            entries = [
                {"id": r.id, "key": r.key, "refresh": r.refresh}
                for r in self._pending
                if r.status == "queued"
            ]
        _save_durable_queue(entries)

    def _latest_history_for_key(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            for h in self._history:
                if h.get("key") == key:
                    return h
        return None

    def _restore_durable_queue(self) -> None:
        history_ids = {h.get("id") for h in self._history}
        restored = 0
        for entry in _load_durable_queue():
            key = entry.get("key")
            if not key or key not in FETCHERS:
                continue
            if entry.get("id") in history_ids:
                continue
            latest = self._latest_history_for_key(key)
            if latest and latest.get("status") == "done":
                continue
            try:
                self.submit(key, refresh=bool(entry.get("refresh")))
                restored += 1
            except ValueError:
                break
        if restored:
            print(f"[runs] restored {restored} queued run(s) from durable queue", file=sys.stderr)

    def _prune_runs_by_id(self) -> None:
        with self._lock:
            if len(self._runs_by_id) <= MAX_HISTORY:
                return
            keep_ids = {r.id for r in self._pending}
            keep_ids.update(h.get("id") for h in self._history if h.get("id"))
            for rid in list(self._runs_by_id):
                if rid not in keep_ids:
                    del self._runs_by_id[rid]

    def _append_history(self, summary: dict[str, Any], *, profile_id: str) -> None:
        hist_file = runs_dir(profile_id=profile_id) / "history.json"
        entries = _load_run_history_from(hist_file)
        entries.insert(0, summary)
        _save_run_history_to(hist_file, entries)
        with self._lock:
            if profile_id == get_active_profile_id():
                self._history.appendleft(summary)
                while len(self._history) > MAX_HISTORY:
                    self._history.pop()

    def _register_active_process(self, run: Run, pid: int) -> None:
        entry = {
            "id": run.id,
            "pid": pid,
            "key": run.key,
            "label": run.label,
            "started_at": run.started_at,
        }
        active = [e for e in _read_active_runs() if e.get("id") != run.id]
        active.append(entry)
        _write_active_runs(active)

    def _unregister_active_process(self, run_id: str) -> None:
        active = [e for e in _read_active_runs() if e.get("id") != run_id]
        _write_active_runs(active)

    def _reap_orphan_processes(self) -> None:
        for entry in _read_active_runs():
            pid = int(entry.get("pid") or 0)
            if _pid_alive(pid):
                _terminate_pid(pid)
            summary = {
                "id": entry.get("id", "?"),
                "key": entry.get("key", "?"),
                "label": entry.get("label", "?"),
                "status": "failed",
                "started_at": entry.get("started_at"),
                "ended_at": time.time(),
                "exit_code": -1,
                "line_count": 0,
                "note": "orphaned — previous server stopped while this fetcher was running",
            }
            self._append_history(summary, profile_id=get_active_profile_id())
        _write_active_runs([])

    def shutdown(self) -> None:
        self._watchdog_stop.set()
        with self._lock:
            pending = list(self._pending)
            active = self._active
        kill_pids: list[int] = []
        for run in pending:
            changed, pids = run.cancel()
            if changed:
                kill_pids.extend(self._collect_pids_for_run(run, pids))
        if active is not None:
            changed, pids = active.cancel()
            if changed:
                kill_pids.extend(self._collect_pids_for_run(active, pids))
        if kill_pids:
            for pid in dict.fromkeys(kill_pids):
                _terminate_pid(pid)
        _write_active_runs([])
        _save_durable_queue([])
        self.join_threads(timeout=5.0)

    def join_threads(self, timeout: float = 5.0) -> None:
        """Stop watchdog and wait for worker/watchdog threads (bounded)."""
        self._watchdog_stop.set()
        wt = getattr(self, "_watchdog_thread", None)
        if wt is not None and wt.is_alive():
            wt.join(timeout=timeout)
        if self._worker_thread.is_alive():
            self._worker_thread.join(timeout=timeout)

    def submit(self, key: str, *, refresh: bool = False) -> Run:
        if key not in FETCHERS:
            raise KeyError(key)
        with self._lock:
            active = self._active
            if active and active.key == key and active.status in _IN_FLIGHT_STATUSES:
                raise ValueError(f"{key} already queued or running")
            if any(r.key == key and r.status in _IN_FLIGHT_STATUSES for r in self._pending):
                raise ValueError(f"{key} already queued or running")
            in_flight = sum(
                1 for r in self._pending if r.status in _IN_FLIGHT_STATUSES
            )
            # cancel() drops a run from _pending while the worker is still
            # finishing it on _active — count that slot so the queue can't wedge.
            if (
                active
                and active.status in _IN_FLIGHT_STATUSES
                and active not in self._pending
            ):
                in_flight += 1
            if in_flight >= 2:
                raise ValueError(
                    "queue full — one run is in progress and one is queued; "
                    "wait for a slot before submitting another"
                )
            profile_id = get_active_profile_id()
            run = Run(
                key,
                refresh=refresh,
                runs_dir=runs_dir(profile_id=profile_id),
                profile_id=profile_id,
            )
            self._pending.append(run)
            self._runs_by_id[run.id] = run
            self._queue.put(run)
        self._persist_queue()
        self._ensure_worker_thread()
        return run

    def cancel(self, run_id: str) -> tuple[Run | None, str | None]:
        with self._lock:
            run = self._runs_by_id.get(run_id)
            if run is None:
                return None, "not_found"
            if run.status in ("done", "failed", "cancelled") or run._finished.is_set():
                return None, "already_finished"
        changed, proc_pids = run.cancel()
        if not changed:
            return None, "already_finished"
        pids = self._collect_pids_for_run(run, proc_pids)
        with self._lock:
            if run in self._pending:
                self._pending.remove(run)
        self._persist_queue()
        if run._finished.is_set():
            self._finalize_run(run)
        elif run.status == "cancelling":
            if pids:
                _kill_pids_async(pids)
            self._schedule_cancel_completion(run)
        return run, None

    def _schedule_cancel_completion(self, run: Run) -> None:
        if self._worker_thread.is_alive():
            threading.Thread(
                target=self._complete_cancel_after_kill,
                args=(run,),
                name=f"run-cancel-{run.id}",
                daemon=True,
            ).start()
        else:
            self._complete_cancel_after_kill(run)

    def cancel_all(self, *, profile_id: str | None = None) -> list[dict[str, Any]]:
        """Cancel every queued or running fetcher (active + next in queue). Returns immediately."""
        with self._lock:
            targets = [
                r for r in self._pending if r.status in _IN_FLIGHT_STATUSES
            ]
            active = self._active
            if (
                active
                and active.status in _IN_FLIGHT_STATUSES
                and active not in targets
            ):
                targets.append(active)
        if profile_id is not None:
            targets = [r for r in targets if r.profile_id == profile_id]
        all_pids: list[int] = []
        summaries: list[dict[str, Any]] = []
        to_finalize_now: list[Run] = []
        to_complete_async: list[Run] = []
        for run in targets:
            changed, proc_pids = run.cancel()
            if not changed:
                continue
            all_pids.extend(self._collect_pids_for_run(run, proc_pids))
            with self._lock:
                if run in self._pending:
                    self._pending.remove(run)
            if run._finished.is_set():
                to_finalize_now.append(run)
            elif run.status == "cancelling":
                to_complete_async.append(run)
            summaries.append(run.to_summary())
        self._persist_queue()
        if all_pids:
            _kill_pids_async(all_pids)
        for run in to_finalize_now:
            self._finalize_run(run)
        for run in to_complete_async:
            self._schedule_cancel_completion(run)
        return summaries

    def force_reset(self, *, profile_id: str | None = None) -> dict[str, Any]:
        """Kill all tracked PIDs, clear queue state, finalize every in-flight run."""
        with self._lock:
            targets = [
                r for r in self._pending if r.status in _IN_FLIGHT_STATUSES
            ]
            active = self._active
            if (
                active
                and active.status in _IN_FLIGHT_STATUSES
                and active not in targets
            ):
                targets.append(active)
        if profile_id is not None:
            targets = [r for r in targets if r.profile_id == profile_id]
        all_pids: list[int] = []
        for entry in _read_active_runs():
            pid = int(entry.get("pid") or 0)
            if pid > 0:
                all_pids.append(pid)
        for run in targets:
            run.cancelled = True
            with run._lock:
                if run.status in _IN_FLIGHT_STATUSES and not run._finished.is_set():
                    run.status = "cancelled"
                    run.exit_code = -1
                    run.ended_at = time.time()
            all_pids.extend(self._collect_pids_for_run(run, []))
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        with self._lock:
            self._pending.clear()
            self._active = None
        _write_active_runs([])
        _save_durable_queue([])
        if all_pids:
            _kill_pids_async(list(dict.fromkeys(all_pids)))
        summaries: list[dict[str, Any]] = []
        for run in targets:
            if not run._finished.is_set():
                run.mark_finished()
                run.broadcast(
                    "done",
                    {
                        "status": "cancelled",
                        "exit_code": run.exit_code or -1,
                        "started_at": run.started_at,
                        "ended_at": run.ended_at,
                    },
                )
            self._finalize_run(run)
            summaries.append(run.to_summary())
        self._ensure_worker_thread()
        return {"cancelled": summaries, "force": True}

    def has_runs_for_profile(self, profile_id: str) -> bool:
        """True if any queued or running fetcher is bound to this profile."""
        with self._lock:
            return any(
                r.profile_id == profile_id and r.status in _IN_FLIGHT_STATUSES
                for r in self._pending
            )

    def cancel_all_and_wait(
        self,
        timeout: float = SWITCH_CANCEL_WAIT_SEC,
    ) -> dict[str, Any]:
        """Cancel every in-flight fetcher and wait for each to finish (bounded)."""
        with self._lock:
            targets = [
                r for r in self._pending if r.status in _IN_FLIGHT_STATUSES
            ]
        cancelled: list[dict[str, Any]] = []
        for run in targets:
            run_obj, err = self.cancel(run.id)
            if run_obj is not None and err is None:
                cancelled.append(run_obj.to_summary())
        deadline = time.monotonic() + timeout
        stragglers: list[dict[str, Any]] = []
        for run in targets:
            remaining = deadline - time.monotonic()
            if remaining > 0:
                run._finished.wait(remaining)
            if not run._finished.is_set():
                stragglers.append(run.to_summary())
        if stragglers:
            ids = ", ".join(s.get("id", "?") for s in stragglers)
            print(
                f"WARN: {len(stragglers)} run(s) still not finished after "
                f"{timeout}s cancel wait: {ids}",
                file=sys.stderr,
                flush=True,
            )
        return {"cancelled": cancelled, "stragglers": stragglers}

    def get(self, run_id: str) -> Run | None:
        with self._lock:
            return self._runs_by_id.get(run_id)

    def snapshot(self) -> dict[str, Any]:
        self._kick_queue_if_stalled_throttled()
        with self._lock:
            active = (
                self._active.to_summary()
                if self._active and self._active.status in ("launching", "running", "cancelling")
                else None
            )
            queued = [r.to_summary() for r in self._pending if r.status == "queued"]
            history = list(self._history)
        return {"active": active, "queue": queued, "history": history}

    def _finalize_run(self, run: Run) -> None:
        with run._lock:
            if run._finalized:
                return
            run._finalized = True
        if not run._finished.is_set():
            if run.ended_at is None:
                run.ended_at = time.time()
            run.mark_finished()
            run.broadcast(
                "done",
                {
                    "status": run.status,
                    "exit_code": run.exit_code,
                    "started_at": run.started_at,
                    "ended_at": run.ended_at,
                },
            )
        with self._lock:
            if self._active is run:
                self._active = None
            if run in self._pending:
                self._pending.remove(run)
        self._unregister_active_process(run.id)
        self._append_history(run.to_summary(), profile_id=run.profile_id)
        self._persist_queue()
        self._prune_runs_by_id()

    def _worker_loop(self) -> None:
        while True:
            try:
                run = self._queue.get()
                if not run._finished.is_set():
                    with self._lock:
                        self._active = run
                        if run.status == "queued":
                            run.status = "launching"
                    self._persist_queue()
                    try:
                        if run.status != "cancelled":
                            self._execute(run)
                    except Exception as exc:  # noqa: BLE001 - surface anything the subprocess plumbing might raise.
                        if not run.cancelled:
                            run.status = "failed"
                            run.exit_code = -1
                            run.add_line("stderr", f"[server] worker error: {exc!r}")
                self._finalize_run(run)
            except Exception as exc:  # noqa: BLE001 - keep the worker alive
                print(f"[runs] worker loop error: {exc!r}", file=sys.stderr, flush=True)
                time.sleep(0.5)

    def _execute(self, run: Run) -> None:
        if run.cancelled:
            run.status = "cancelled"
            run.exit_code = -1
            return

        argv = run.argv()
        run.status = "launching"
        run.started_at = time.time()
        run.broadcast("status", {"status": run.status, "started_at": run.started_at})
        run.add_line("stdout", f"$ {' '.join(argv)}")

        try:
            from auth.manager import subprocess_env_for_profile

            env = subprocess_env_for_profile(run.profile_id)
        except Exception as exc:
            run.status = "failed"
            run.exit_code = -1
            run.add_line("stderr", f"[server] failed to build subprocess env: {exc!r}")
            return

        # Run Popen on a launcher thread so a wedged CreateProcess can't wedge
        # the queue worker. If the launch doesn't return within
        # LAUNCH_TIMEOUT_SEC the run is marked failed and the worker moves on
        # to the next queued item; late launches are terminated immediately.
        launch_q: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)
        launch_abandoned = threading.Event()

        def _launch() -> None:
            try:
                p = popen_fetcher(  # noqa: S603 - argv is fixed in FETCHERS, not user input
                    argv,
                    # Run from repo root so the relative script path in argv resolves;
                    # profile scoping is via BAKLOG_PROFILE in env + resolve_catalog_path,
                    # not cwd (profiles/<id>/ holds data/cache, not the fetch_*.py scripts).
                    cwd=str(ROOT),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    bufsize=1,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=env,
                )
            except BaseException as e:  # noqa: BLE001 - surface any launch failure to the worker
                if not launch_abandoned.is_set():
                    launch_q.put(("err", e))
                return
            if launch_abandoned.is_set():
                if p.poll() is None and p.pid:
                    _terminate_pid(p.pid)
                run.add_line(
                    "stderr",
                    "[server] late launch after timeout — terminated stray subprocess",
                )
                return
            launch_q.put(("ok", p))

        threading.Thread(target=_launch, name=f"run-launch-{run.id}", daemon=True).start()
        try:
            tag, payload = launch_q.get(timeout=LAUNCH_TIMEOUT_SEC)
        except queue.Empty:
            launch_abandoned.set()
            run.status = "failed"
            run.exit_code = -1
            run.add_line(
                "stderr",
                f"[server] subprocess launch did not return within {LAUNCH_TIMEOUT_SEC}s "
                f"(likely Windows AppX Python activation deadlock); abandoning the launcher thread. "
                f"Restart the server if subsequent runs also fail to start.",
            )
            return
        if run.cancelled or run._finished.is_set():
            if tag == "ok" and payload is not None and payload.poll() is None and payload.pid:
                _terminate_pid(payload.pid)
            run.status = "cancelled"
            run.exit_code = -1
            run.add_line("stderr", "[server] cancelled during launch")
            return
        if tag == "err":
            exc = payload
            if isinstance(exc, FileNotFoundError):
                run.status = "failed"
                run.exit_code = -1
                run.add_line("stderr", f"[server] cannot launch: {exc}")
                return
            run.status = "failed"
            run.exit_code = -1
            run.add_line("stderr", f"[server] launch error: {exc!r}")
            return
        proc = payload

        if run.cancelled:
            if proc.poll() is None and proc.pid:
                _terminate_pid(proc.pid)
            run.status = "cancelled"
            run.exit_code = -1
            return

        run._proc = proc
        run.status = "running"
        run.broadcast("status", {"status": run.status, "started_at": run.started_at})
        if proc.pid:
            self._register_active_process(run, proc.pid)
        assert proc.stdout is not None

        line_queue: queue.Queue[str | None] = queue.Queue()

        def _reader() -> None:
            try:
                for raw in proc.stdout:
                    line_queue.put(raw.rstrip("\n"))
            finally:
                line_queue.put(None)

        threading.Thread(target=_reader, daemon=True).start()

        last_line_at = time.monotonic()
        last_stall_notice_at = 0.0
        run_started_mono = time.monotonic()
        max_runtime_killed = False
        reader_done = False

        while not reader_done:
            if run.cancelled:
                break
            try:
                line = line_queue.get(timeout=STALL_POLL_SEC)
            except queue.Empty:
                line = "__POLL__"
            now = time.monotonic()
            if line == "__POLL__":
                if proc.poll() is not None and line_queue.empty():
                    break
                elapsed = now - run_started_mono
                if elapsed >= MAX_RUN_SECONDS:
                    run.add_line(
                        "stderr",
                        f"[server] exceeded maximum runtime ({int(MAX_RUN_SECONDS)}s) — "
                        f"force-killing PID {proc.pid}",
                    )
                    if proc.pid:
                        _terminate_pid(proc.pid)
                    try:
                        proc.wait(timeout=TERMINATE_GRACE_SEC)
                    except Exception:  # noqa: BLE001
                        pass
                    max_runtime_killed = True
                    break
                silent = now - last_line_at
                if silent >= SILENT_STALL_KILL_SEC:
                    run.add_line(
                        "stderr",
                        f"[server] no output for {int(silent)}s — force-killing PID {proc.pid}",
                    )
                    if proc.pid:
                        _terminate_pid(proc.pid)
                    try:
                        proc.wait(timeout=TERMINATE_GRACE_SEC)
                    except Exception:  # noqa: BLE001
                        pass
                    break
                if silent >= STALL_FIRST_NOTICE_SEC and (
                    last_stall_notice_at == 0.0
                    or now - last_stall_notice_at >= STALL_REPEAT_SEC
                ):
                    sec = int(silent)
                    run.add_line(
                        "stderr",
                        f"[server] no output for {sec}s — still running (PID {proc.pid})",
                    )
                    last_stall_notice_at = now
                continue
            if line is None:
                reader_done = True
                break
            run.add_line("stdout", line)
            last_line_at = now
            last_stall_notice_at = 0.0

        # On cancel the HTTP thread already issued _terminate_pid(); re-issue
        # here in case that missed (Windows AppX Python can survive the first
        # taskkill), then never block the worker indefinitely — a lingering
        # zombie must not wedge the queue. We finalize after a bounded wait so
        # the next queued run can start regardless.
        if run.cancelled and proc.poll() is None:
            if proc.pid:
                _terminate_pid(proc.pid)
            try:
                proc.wait(timeout=TERMINATE_GRACE_SEC)
            except Exception:  # noqa: BLE001 - subprocess.TimeoutExpired or platform variants
                run.add_line(
                    "stderr",
                    f"[server] PID {proc.pid} did not exit after kill; "
                    f"abandoning it and advancing the queue",
                )
        else:
            try:
                proc.wait(timeout=TERMINATE_GRACE_SEC)
            except Exception:  # noqa: BLE001
                if proc.pid:
                    _terminate_pid(proc.pid)
        run.exit_code = proc.returncode if proc.returncode is not None else -1
        if max_runtime_killed:
            run.status = "failed"
            run.exit_code = -1
        elif run.cancelled:
            run.status = "cancelled"
            run.add_line("stderr", "[server] cancelled")
        elif proc.returncode == 0:
            run.status = "done"
        else:
            run.status = "failed"
        run._proc = None


MANAGER = RunManager()


def _header_hostname(value: str | None) -> str | None:
    if not value:
        return None
    host = (urlparse(value).hostname or "").lower()
    return host or None


def _request_host_is_local(handler: SimpleHTTPRequestHandler) -> bool:
    host_header = handler.headers.get("Host", "")
    hostname = host_header.split(":")[0].strip().lower()
    return hostname in _LOCAL_HOSTNAMES


def _origin_is_local(handler: SimpleHTTPRequestHandler) -> bool:
    for name in ("Origin", "Referer"):
        host = _header_hostname(handler.headers.get(name))
        if host in _LOCAL_HOSTNAMES:
            return True
    return False


def _csrf_allowed(handler: SimpleHTTPRequestHandler) -> bool:
    """Block cross-site POST/PUT/DELETE to localhost while the dev server runs."""
    from shared.supabase_auth import auth_enabled, verify_bearer_user

    if auth_enabled() and verify_bearer_user(handler.headers.get("Authorization")):
        return True
    if not _request_host_is_local(handler):
        return False
    if handler.headers.get(_BAKLOG_LOCAL_HEADER) == "1":
        return True
    return _origin_is_local(handler)


def _send_json(handler: SimpleHTTPRequestHandler, status: int, payload: Any) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def _send_bytes(
    handler: SimpleHTTPRequestHandler,
    status: int,
    body: bytes,
    *,
    content_type: str,
    filename: str | None = None,
) -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    if filename:
        handler.send_header("Content-Disposition", f'attachment; filename="{filename}"')
    handler.end_headers()
    handler.wfile.write(body)


def _sse_format(event: str, data: Any, *, event_id: int | str | None = None) -> bytes:
    payload = data if isinstance(data, str) else json.dumps(data)
    parts: list[str] = []
    if event_id is not None:
        parts.append(f"id: {event_id}")
    parts.append(f"event: {event}")
    parts.append(f"data: {payload}")
    parts.append("")
    return ("\n".join(parts) + "\n").encode("utf-8")


def _stream_resume_since(handler: SimpleHTTPRequestHandler) -> int:
    """Parse SSE resume cursor from ?since= and Last-Event-ID (max of both)."""
    since = 0
    parsed = urlparse(handler.path)
    raw = parse_qs(parsed.query).get("since", [None])[0]
    if raw is not None:
        try:
            since = max(0, int(raw))
        except (TypeError, ValueError):
            pass
    last_event = handler.headers.get("Last-Event-ID") or handler.headers.get("Last-Event-Id")
    if last_event:
        try:
            since = max(since, int(last_event.strip()))
        except ValueError:
            pass
    return since


# Known catalog files the dashboard probes on boot. When a store hasn't been
# fetched yet the file simply doesn't exist — return an empty catalog instead
# of 404 so the browser console stays clean during the connection pass.
_LIBRARY_JSON_RE = re.compile(r"^/games_[a-z0-9_]+\.json$", re.I)


def _path_only(handler: SimpleHTTPRequestHandler) -> str:
    return handler.path.split("?", 1)[0]


def _normalize_static_path(path_only: str) -> str:
    clean = path_only.split("?", 1)[0]
    if not clean.startswith("/"):
        clean = "/" + clean.lstrip("/")
    return clean


def _static_class(path_only: str) -> str:
    """Classify a non-API path: public | data | deny."""
    clean = _normalize_static_path(path_only)
    parts = [p for p in clean.split("/") if p]
    if any(p.startswith(".") for p in parts):
        return "deny"
    if parts and parts[0] == "profiles":
        return "deny"
    if parts and parts[0] == "data":
        return "deny"
    if len(parts) >= 2 and parts[0] == "cache":
        if parts[1] == "auth":
            return "deny"
        if parts[1] in PROFILE_CACHE_JSON_FILES:
            return "data"
        return "deny"
    if _LIBRARY_JSON_RE.match(clean) or clean.lower() == "/itad_prices.json":
        return "data"
    return "public"


def _send_auth_required(handler: SimpleHTTPRequestHandler) -> None:
    if handler.command.upper() == "HEAD":
        handler.send_response(HTTPStatus.UNAUTHORIZED)
        handler.end_headers()
    else:
        _send_json(handler, HTTPStatus.UNAUTHORIZED, {"error": "sign in required"})


def _bind_request_user(handler: SimpleHTTPRequestHandler) -> str | None:
    """Verify bearer, ensure profile dir, pin request context. None after 401."""
    from shared.account_profiles import ensure_profile_for_user
    from shared.supabase_auth import verify_bearer_user

    user = verify_bearer_user(handler.headers.get("Authorization"))
    if not user:
        _send_auth_required(handler)
        return None
    pid = ensure_profile_for_user(user["id"], user.get("email") or None)
    set_request_profile_id(pid)
    return pid


def _bind_bearer_profile(handler: SimpleHTTPRequestHandler) -> bool:
    """Verify bearer and pin request profile. Return False after sending 401."""
    return _bind_request_user(handler) is not None


def _gate_static(handler: SimpleHTTPRequestHandler) -> bool:
    """Gate static catalog/cache paths when Supabase auth is on. Return False if handled."""
    from shared.supabase_auth import auth_enabled

    path_only = _path_only(handler)
    kind = _static_class(path_only)
    if kind == "deny":
        handler.send_error(HTTPStatus.NOT_FOUND, "Not found")
        return False
    if kind == "data" and auth_enabled():
        return _bind_bearer_profile(handler)
    return True


def _maybe_serve_empty_library_json(handler: SimpleHTTPRequestHandler, path: str) -> bool:
    if not _LIBRARY_JSON_RE.match(path):
        return False
    filename = path.lstrip("/")
    if catalog_path(filename).is_file():
        return False
    _send_json(handler, HTTPStatus.OK, {"game_count": 0, "games": []})
    return True


def _read_json_body(handler: SimpleHTTPRequestHandler) -> tuple[dict[str, Any] | None, str | None]:
    try:
        length = int(handler.headers.get("Content-Length") or 0)
    except ValueError:
        return None, "invalid Content-Length"
    if length <= 0:
        return None, "empty body"
    if length > PERSONAL_MAX_BYTES:
        return None, f"body too large ({length} > {PERSONAL_MAX_BYTES})"
    try:
        raw = handler.rfile.read(length).decode("utf-8")
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"invalid JSON: {exc!r}"
    if not isinstance(payload, dict):
        return None, "payload must be a JSON object"
    return payload, None


def _api_path(handler: SimpleHTTPRequestHandler) -> str:
    return handler.path.split("?", 1)[0]


def _require_api_auth(handler: SimpleHTTPRequestHandler) -> bool:
    """Authenticate /api/* when Supabase auth is enabled. Return False if rejected."""
    from shared.supabase_auth import auth_enabled

    path = _api_path(handler)
    if not path.startswith("/api/"):
        return True
    if path == "/api/config":
        return True
    if not auth_enabled():
        return True
    return _bind_request_user(handler) is not None


def _profile_admin_blocked() -> bool:
    from shared.supabase_auth import auth_enabled

    return auth_enabled()


def _run_accessible(run: Run | None) -> Run | None:
    """When account auth is on, only the bound profile may access a run."""
    from shared.supabase_auth import auth_enabled

    if run is None:
        return None
    if not auth_enabled():
        return run
    if run.profile_id == get_active_profile_id():
        return run
    return None


class Handler(SimpleHTTPRequestHandler):
    def handle(self) -> None:
        try:
            super().handle()
        finally:
            clear_request_profile_id()

    def _reject_if_csrf(self) -> bool:
        """Return True when the request was rejected (caller should return)."""
        if _csrf_allowed(self):
            return False
        _send_json(
            self,
            HTTPStatus.FORBIDDEN,
            {"error": "cross-origin request blocked — open BAKLOG from http://127.0.0.1 and retry"},
        )
        return True

    server_version = "SteamBacklogDev/1.0"

    # Static assets that change during frontend work — never cache in dev so a
    # normal reload can't serve a mix of old and new ES modules (e.g. bind-events
    # calling fetcherRunner.reopenLogPanel while fetcher-health.js is still stale).
    # .html is included because index.html ships an inline FOUC script that
    # drives the boot curtain — a stale cached HTML can keep the curtain in
    # an outdated state even after the JS bundle is refreshed.
    _NO_CACHE_SUFFIXES = (".js", ".mjs", ".css", ".html")

    def end_headers(self) -> None:
        path = self.path.split("?", 1)[0].lower()
        # Root path serves index.html, which has no suffix — treat it the same.
        if path.endswith(self._NO_CACHE_SUFFIXES) or path == "/" or path == "":
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def translate_path(self, path: str) -> str:
        """Serve catalog and cache JSON from the active profile root (legacy or profiles/<id>/)."""
        clean = path.split("?", 1)[0].lstrip("/")
        if _static_class("/" + clean) == "deny":
            return str(profile_root() / ".profile_static_blocked" / clean)
        if clean.startswith("profiles/"):
            # Block direct static access to another profile's tree (use top-level paths).
            return str(profile_root() / ".profile_static_blocked" / clean)
        if _LIBRARY_JSON_RE.match("/" + clean) or clean == "itad_prices.json":
            disk = catalog_path(clean) if clean != "itad_prices.json" else catalog_path("itad_prices.json")
            if disk.is_file():
                return str(disk)
        if clean.startswith("cache/"):
            name = clean.split("/", 1)[1]
            if name in PROFILE_CACHE_JSON_FILES:
                # Always resolve to the active profile's cache path. For a legacy
                # (default) layout this is repo-root cache; for profiles/<id>/ it
                # is the profile cache. A missing file 404s instead of leaking the
                # default profile's enrichment data into another profile's chips.
                return str(cache_json_path(name))
        return super().translate_path(path)

    def _begin_request(self) -> None:
        clear_request_profile_id()

    # ---- routing -----------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802 - http.server API
        self._begin_request()
        path = _api_path(self)
        if path == "/api/config":
            self._handle_config_get()
            return
        if path.startswith("/oauth/epic/callback"):
            self._handle_epic_oauth_callback()
            return
        if path.startswith("/api/stream/"):
            if not _authorize_stream(self):
                return
            self._handle_stream(path[len("/api/stream/"):])
            return
        if path.startswith("/api/auth/") and path.endswith("/stream"):
            if not _authorize_stream(self):
                return
            rest = path[len("/api/auth/") : -len("/stream")].strip("/")
            self._handle_auth_stream(rest)
            return
        if not _require_api_auth(self):
            return
        if path == "/api/runs":
            self._handle_runs()
            return
        if path == "/api/fetchers":
            self._handle_fetchers()
            return
        if path == "/api/personal":
            self._handle_personal_get()
            return
        if path == "/api/profiles":
            self._handle_profiles_get()
            return
        if path == "/api/auth/session":
            self._handle_auth_session_get()
            return
        if path == "/api/auth/status":
            self._handle_auth_status()
            return
        path_only = _path_only(self)
        if not _gate_static(self):
            return
        if _maybe_serve_empty_library_json(self, path_only):
            return
        super().do_GET()

    def do_HEAD(self) -> None:  # noqa: N802 - http.server API
        self._begin_request()
        if self.path == "/api/config":
            self._handle_config_get()
            return
        if not _require_api_auth(self):
            return
        if not _gate_static(self):
            return
        super().do_HEAD()

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        self._begin_request()
        if self._reject_if_csrf():
            return
        if not _require_api_auth(self):
            return
        if _api_path(self) == "/api/auth/stream-ticket":
            self._handle_stream_ticket_mint()
            return
        if self.path.rstrip("/") == "/api/runs/cancel":
            self._handle_cancel_all()
            return
        if self.path.startswith("/api/run/"):
            rest = self.path[len("/api/run/"):].strip("/")
            if rest.endswith("/cancel"):
                run_id = rest[: -len("/cancel")].strip("/")
                self._handle_cancel(run_id)
            else:
                self._handle_submit(rest)
            return
        if self.path.startswith("/api/auth/") and _api_path(self).endswith("/start"):
            provider = _api_path(self)[len("/api/auth/") : -len("/start")].strip("/")
            self._handle_auth_start(provider)
            return
        if self.path.startswith("/api/auth/") and self.path.endswith("/oauth-url"):
            provider = self.path[len("/api/auth/") : -len("/oauth-url")].strip("/")
            if provider == "epic":
                self._handle_epic_oauth_url()
            else:
                _send_json(self, HTTPStatus.NOT_FOUND, {"error": f"no oauth-url for {provider}"})
            return
        if self.path.startswith("/api/auth/") and self.path.endswith("/open-url"):
            provider = self.path[len("/api/auth/") : -len("/open-url")].strip("/")
            self._handle_auth_open_url(provider)
            return
        if self.path.startswith("/api/auth/") and self.path.endswith("/disconnect"):
            provider = self.path[len("/api/auth/") : -len("/disconnect")].strip("/")
            self._handle_auth_disconnect(provider)
            return
        if self.path.startswith("/api/auth/") and self.path.endswith("/enable"):
            provider = self.path[len("/api/auth/") : -len("/enable")].strip("/")
            self._handle_auth_enable(provider)
            return
        if self.path == "/api/auth/master-password":
            self._handle_auth_master_password()
            return
        if self.path == "/api/auth/secrets/export":
            self._handle_auth_secrets_export()
            return
        if self.path.startswith("/api/auth/secrets/import"):
            self._handle_auth_secrets_import()
            return
        if self.path == "/api/profiles":
            self._handle_profiles_create()
            return
        if self.path == "/api/profiles/active":
            self._handle_profiles_set_active()
            return
        if self.path == "/api/personal":
            self._handle_personal_put()
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")

    def do_DELETE(self) -> None:  # noqa: N802 - http.server API
        self._begin_request()
        if self._reject_if_csrf():
            return
        if not _require_api_auth(self):
            return
        path_only = self.path.split("?", 1)[0]
        if path_only.startswith("/api/profiles/"):
            profile_id = path_only[len("/api/profiles/") :].strip("/")
            if profile_id and profile_id not in ("active",):
                self._handle_profiles_delete(profile_id)
                return
        self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")

    def do_PUT(self) -> None:  # noqa: N802 - http.server API
        self._begin_request()
        if self._reject_if_csrf():
            return
        if not _require_api_auth(self):
            return
        if self.path == "/api/personal":
            self._handle_personal_put()
            return
        path_only = self.path.split("?", 1)[0]
        if path_only.startswith("/api/profiles/"):
            profile_id = path_only[len("/api/profiles/") :].strip("/")
            if profile_id and profile_id not in ("active",):
                self._handle_profiles_rename(profile_id)
                return
        if self.path.startswith("/api/auth/") and self.path.endswith("/credentials"):
            provider = self.path[len("/api/auth/") : -len("/credentials")].strip("/")
            self._handle_auth_credentials(provider)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")

    # ---- handlers ----------------------------------------------------------
    def _handle_config_get(self) -> None:
        from shared.supabase_auth import public_auth_config

        _send_json(self, HTTPStatus.OK, public_auth_config())

    def _handle_fetchers(self) -> None:
        try:
            try:
                from dotenv import load_dotenv

                load_dotenv(ROOT / ".env", override=True)
            except ImportError:
                pass
            data = {
                "server_platform": sys.platform,
                "fetchers": [
                    {
                        "key": k,
                        "label": v["label"],
                        # argv[1] is now an absolute script path; show just the basename.
                        "cmd": " ".join([Path(v["argv"][1]).name, *v["argv"][2:]]) if len(v["argv"]) > 1 else "",
                        "metaKey": v.get("metaKey", k),
                        "group": v.get("group", "library"),
                        "color": v.get("color"),
                        "requires": v.get("requires") or [],
                        "missing_requirements": _missing_requirements(v.get("requires") or []),
                        "supports_refresh": bool(v.get("refreshArgs")),
                        "platforms": v.get("platforms") or [],
                        "available": platform_supported(v.get("platforms")),
                    }
                    for k, v in FETCHERS.items()
                ],
            }
            _send_json(self, HTTPStatus.OK, data)
        except Exception as exc:  # noqa: BLE001
            _send_json(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

    @staticmethod
    def _parse_run_submit_path(rest: str) -> tuple[str, bool]:
        from urllib.parse import parse_qs

        path, _, qs = rest.partition("?")
        key = path.strip("/").split("/", 1)[0]
        params = parse_qs(qs) if qs else {}
        refresh_val = (params.get("refresh") or ["0"])[0].lower()
        refresh = refresh_val in ("1", "true", "yes")
        return key, refresh

    def _handle_profiles_get(self) -> None:
        try:
            from shared.profiles import profiles_status

            data = profiles_status()
            if _profile_admin_blocked():
                active = get_active_profile_id()
                profiles = data.get("profiles") if isinstance(data.get("profiles"), list) else []
                data["profiles"] = [
                    p for p in profiles if isinstance(p, dict) and p.get("id") == active
                ]
                data["active"] = active
                data["accountAuth"] = True
            _send_json(self, HTTPStatus.OK, data)
        except Exception as exc:  # noqa: BLE001
            _send_json(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

    def _handle_profiles_create(self) -> None:
        if _profile_admin_blocked():
            _send_json(
                self,
                HTTPStatus.FORBIDDEN,
                {"error": "profile management is disabled while account sign-in is enabled"},
            )
            return
        payload, err = _read_json_body(self)
        if err:
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": err})
            return
        assert payload is not None
        try:
            from shared.profiles import create_profile

            created = create_profile(str(payload.get("label") or ""))
            _refresh_personal_paths()
            _send_json(self, HTTPStatus.CREATED, created)
        except ValueError as exc:
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def _handle_profiles_set_active(self) -> None:
        if _profile_admin_blocked():
            _send_json(
                self,
                HTTPStatus.FORBIDDEN,
                {"error": "profile switching is disabled while account sign-in is enabled"},
            )
            return
        payload, err = _read_json_body(self)
        if err:
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": err})
            return
        assert payload is not None
        profile_id = str(payload.get("id") or "").strip()
        if not profile_id:
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": "id is required"})
            return
        try:
            from shared.profiles import set_active_profile

            MANAGER.cancel_all_and_wait()
            result = set_active_profile(profile_id)
            _refresh_personal_paths()
            # BAKLOG_PROFILE in the server process is dropped at import (_release_server_profile_env).
            _send_json(self, HTTPStatus.OK, result)
        except ValueError as exc:
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def _handle_profiles_rename(self, profile_id: str) -> None:
        if _profile_admin_blocked():
            _send_json(
                self,
                HTTPStatus.FORBIDDEN,
                {"error": "profile management is disabled while account sign-in is enabled"},
            )
            return
        payload, err = _read_json_body(self)
        if err:
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": err})
            return
        assert payload is not None
        try:
            from shared.profiles import rename_profile

            updated = rename_profile(profile_id, str(payload.get("label") or ""))
            _send_json(self, HTTPStatus.OK, updated)
        except ValueError as exc:
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def _handle_profiles_delete(self, profile_id: str) -> None:
        if _profile_admin_blocked():
            _send_json(
                self,
                HTTPStatus.FORBIDDEN,
                {"error": "profile management is disabled while account sign-in is enabled"},
            )
            return
        if MANAGER.has_runs_for_profile(profile_id):
            _send_json(
                self,
                HTTPStatus.CONFLICT,
                {
                    "error": (
                        "This profile has a fetch running or queued. "
                        "Cancel its runs or let them finish before deleting."
                    ),
                },
            )
            return
        try:
            from shared.profiles import delete_profile

            delete_profile(profile_id)
            _refresh_personal_paths()
            _send_json(self, HTTPStatus.OK, {"ok": True})
        except ValueError as exc:
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def _handle_personal_get(self) -> None:
        try:
            doc = _load_personal_doc()
        except PersonalCorruptError as exc:
            _send_json(self, HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(exc)})
            return
        except Exception as exc:  # noqa: BLE001 - the file is small, anything is unexpected here
            _send_json(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"load failed: {exc!r}"})
            return
        _send_json(self, HTTPStatus.OK, doc)

    def _handle_personal_put(self) -> None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": "invalid Content-Length"})
            return
        if length <= 0:
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": "empty body"})
            return
        if length > PERSONAL_MAX_BYTES:
            _send_json(
                self,
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                {"error": f"body too large ({length} > {PERSONAL_MAX_BYTES})"},
            )
            return
        try:
            raw = self.rfile.read(length).decode("utf-8")
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": f"invalid JSON: {exc!r}"})
            return
        claimed = payload.get("profile")
        if claimed is not None:
            from shared.profile_paths import get_active_profile_id

            active = get_active_profile_id()
            if str(claimed) != active:
                _send_json(
                    self,
                    HTTPStatus.CONFLICT,
                    {
                        "error": "profile mismatch",
                        "active": active,
                        "claimed": str(claimed),
                    },
                )
                return
        try:
            doc = _save_personal_doc(payload)
        except PersonalCorruptError as exc:
            _send_json(self, HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(exc)})
            return
        except ValueError as exc:
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        except OSError as exc:
            _send_json(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"write failed: {exc!r}"})
            return
        _send_json(self, HTTPStatus.OK, doc)

    def _handle_runs(self) -> None:
        snap = MANAGER.snapshot()
        from shared.supabase_auth import auth_enabled

        if auth_enabled():
            pid = get_active_profile_id()
            active = snap.get("active")
            if active and active.get("profile_id") != pid:
                snap["active"] = None
            snap["queue"] = [
                r for r in (snap.get("queue") or []) if r.get("profile_id") == pid
            ]
            snap["history"] = [
                r for r in (snap.get("history") or []) if r.get("profile_id") == pid
            ]
        _send_json(self, HTTPStatus.OK, snap)

    def _handle_submit(self, rest: str) -> None:
        key, refresh = self._parse_run_submit_path(rest)
        if key not in FETCHERS:
            _send_json(self, HTTPStatus.NOT_FOUND, {"error": f"unknown fetcher: {key}"})
            return
        fetcher_platforms = FETCHERS[key].get("platforms")
        if not platform_supported(fetcher_platforms):
            allowed = ", ".join(fetcher_platforms or [])
            _send_json(self, HTTPStatus.BAD_REQUEST, {
                "error": f"{FETCHERS[key]['label']} is only available on {allowed} "
                         f"(this server runs on {sys.platform})."
            })
            return
        if refresh and not FETCHERS[key].get("refreshArgs"):
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": f"{key} does not support refresh"})
            return
        try:
            run = MANAGER.submit(key, refresh=refresh)
        except ValueError as exc:
            _send_json(self, HTTPStatus.CONFLICT, {"error": str(exc)})
            return
        _send_json(self, HTTPStatus.ACCEPTED, {
            "run_id": run.id,
            "key": run.key,
            "label": run.label,
            "status": run.status,
        })

    def _handle_cancel(self, run_id: str) -> None:
        run_id = run_id.strip("/").split("/", 1)[0]
        if _run_accessible(MANAGER.get(run_id)) is None:
            _send_json(self, HTTPStatus.NOT_FOUND, {"error": f"unknown run: {run_id}"})
            return
        run, err = MANAGER.cancel(run_id)
        if err == "not_found":
            _send_json(self, HTTPStatus.NOT_FOUND, {"error": f"unknown run: {run_id}"})
            return
        if err == "already_finished":
            _send_json(self, HTTPStatus.CONFLICT, {"error": "run already finished"})
            return
        assert run is not None
        _send_json(self, HTTPStatus.OK, run.to_summary())

    def _handle_cancel_all(self) -> None:
        from shared.supabase_auth import auth_enabled

        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        force_vals = qs.get("force", ["0"])
        force = force_vals[0].lower() in ("1", "true", "yes")
        scope_pid = get_active_profile_id() if auth_enabled() else None
        if force:
            payload = MANAGER.force_reset(profile_id=scope_pid)
        else:
            payload = {"cancelled": MANAGER.cancel_all(profile_id=scope_pid)}
        _send_json(self, HTTPStatus.OK, payload)

    def _handle_auth_session_get(self) -> None:
        """Lightweight account session probe (JWT + bound profile)."""
        from shared.profile_paths import get_active_profile_id
        from shared.supabase_auth import verify_bearer_user

        user = verify_bearer_user(self.headers.get("Authorization"))
        if not user:
            _send_auth_required(self)
            return
        _send_json(
            self,
            HTTPStatus.OK,
            {
                "ok": True,
                "email": user.get("email") or "",
                "profile": get_active_profile_id(),
            },
        )

    def _handle_stream_ticket_mint(self) -> None:
        """Single-use ticket for EventSource streams (cannot send Authorization)."""
        ticket = _mint_stream_ticket(get_active_profile_id())
        _send_json(self, HTTPStatus.OK, {"ticket": ticket})

    def _handle_auth_status(self) -> None:
        try:
            from auth.manager import get_status
            from auth.secrets import secrets_store_corrupt

            _send_json(
                self,
                HTTPStatus.OK,
                {
                    "server_platform": sys.platform,
                    "providers": get_status(),
                    "secrets_corrupt": secrets_store_corrupt(),
                },
            )
        except Exception as exc:  # noqa: BLE001
            _send_json(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

    def _handle_auth_open_url(self, provider: str) -> None:
        try:
            from auth.manager import open_manual_signin

            result = open_manual_signin(provider)
            _send_json(self, HTTPStatus.OK, result)
        except KeyError:
            _send_json(self, HTTPStatus.NOT_FOUND, {"error": f"unknown provider: {provider}"})
        except ValueError as exc:
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            _send_json(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

    def _handle_auth_start(self, provider: str) -> None:
        try:
            from auth.manager import start_browser_auth

            params = parse_qs(urlparse(self.path).query)
            fresh = (params.get("fresh") or ["0"])[0].lower() in ("1", "true", "yes")
            session_id = start_browser_auth(provider, fresh=fresh)
            _send_json(self, HTTPStatus.ACCEPTED, {"session_id": session_id, "provider": provider})
        except KeyError:
            _send_json(self, HTTPStatus.NOT_FOUND, {"error": f"unknown provider: {provider}"})
        except ValueError as exc:
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            _send_json(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

    def _public_callback_url(self, path: str) -> str:
        """Build an absolute URL to ``path`` from the request Host (tunnel-aware)."""
        host = self.headers.get("Host") or f"{HOST}:{PORT}"
        proto = (self.headers.get("X-Forwarded-Proto") or "http").strip().lower()
        if proto not in ("http", "https"):
            proto = "http"
        return f"{proto}://{host}{path}"

    def _handle_epic_oauth_url(self) -> None:
        """Mint a profile-bound OAuth state and return the Epic browser sign-in URL."""
        try:
            from epic_client import build_epic_oauth_login_url

            state = secrets.token_urlsafe(24)
            _register_epic_oauth_state(state, profile_id=get_active_profile_id())
            redirect_uri = self._public_callback_url("/oauth/epic/callback")
            url = build_epic_oauth_login_url(redirect_uri, state)
            _send_json(self, HTTPStatus.OK, {"url": url, "state": state})
        except Exception as exc:  # noqa: BLE001
            _send_json(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

    def _handle_auth_disconnect(self, provider: str) -> None:
        try:
            from auth.manager import disconnect

            disconnect(provider)
            _send_json(self, HTTPStatus.OK, {"ok": True})
        except KeyError:
            _send_json(self, HTTPStatus.NOT_FOUND, {"error": f"unknown provider: {provider}"})
        except Exception as exc:  # noqa: BLE001
            _send_json(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

    def _handle_auth_enable(self, provider: str) -> None:
        try:
            from auth.manager import enable_local

            enable_local(provider)
            _send_json(self, HTTPStatus.OK, {"ok": True})
        except KeyError:
            _send_json(self, HTTPStatus.NOT_FOUND, {"error": f"unknown provider: {provider}"})
        except ValueError as exc:
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            _send_json(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

    def _handle_auth_credentials(self, provider: str) -> None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": "invalid Content-Length"})
            return
        if length <= 0 or length > 65536:
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": "invalid body size"})
            return
        try:
            raw = self.rfile.read(length).decode("utf-8")
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": f"invalid JSON: {exc!r}"})
            return
        try:
            from auth.manager import set_form_credentials

            fields = payload.get("fields") if isinstance(payload, dict) else payload
            if not isinstance(fields, dict):
                raise ValueError("fields must be an object")
            result = set_form_credentials(provider, fields)
            _send_json(self, HTTPStatus.OK, result)
        except KeyError:
            _send_json(self, HTTPStatus.NOT_FOUND, {"error": f"unknown provider: {provider}"})
        except ValueError as exc:
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            _send_json(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

    def _handle_auth_master_password(self) -> None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            payload = json.loads(raw)
            from auth.manager import set_master_password

            set_master_password(payload.get("password"))
            _send_json(self, HTTPStatus.OK, {"ok": True})
        except Exception as exc:  # noqa: BLE001
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def _handle_auth_secrets_export(self) -> None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            payload = json.loads(raw)
            from auth.bundle import BundleError, BundleTooLarge, bundle_filename, export_bundle

            passphrase = (payload.get("passphrase") or "").strip()
            include_profiles = payload.get("include_profiles", True)
            if not isinstance(include_profiles, bool):
                include_profiles = True
            blob = export_bundle(passphrase, include_profiles=include_profiles)
            _send_bytes(
                self,
                HTTPStatus.OK,
                blob,
                content_type="application/octet-stream",
                filename=bundle_filename(),
            )
        except ValueError as exc:
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": str(exc), "code": "invalid_passphrase"})
        except BundleTooLarge as exc:
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": str(exc), "code": "too_large"})
        except BundleError as exc:
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": str(exc), "code": "bundle_error"})
        except Exception as exc:  # noqa: BLE001
            from auth.secrets import SecretsCorruptError

            if isinstance(exc, SecretsCorruptError):
                _send_json(
                    self,
                    HTTPStatus.BAD_REQUEST,
                    {"error": str(exc), "code": "secrets_corrupt"},
                )
                return
            _send_json(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

    def _handle_auth_secrets_import(self) -> None:
        import base64
        from urllib.parse import parse_qs, urlparse

        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            ctype = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
            if ctype == "application/json":
                payload = json.loads(raw.decode("utf-8") if raw else "{}")
                if not isinstance(payload, dict):
                    raise ValueError("import body must be a JSON object")
                passphrase = str(payload.get("passphrase") or "")
                blob_b64 = payload.get("blob")
                if isinstance(blob_b64, str):
                    blob = base64.b64decode(blob_b64, validate=True)
                else:
                    blob = b""
            else:
                parsed = urlparse(self.path)
                params = parse_qs(parsed.query)
                passphrase = (
                    self.headers.get(_BAKLOG_IMPORT_PASSPHRASE_HEADER)
                    or (params.get("passphrase") or [""])[0]
                )
                blob = raw
            from auth.bundle import (
                BadMagic,
                BadPassphrase,
                BundleTooLarge,
                UnsupportedVersion,
                import_bundle,
            )

            summary = import_bundle(blob, passphrase, dry_run=False)
            _send_json(self, HTTPStatus.OK, summary.as_dict())
        except BadPassphrase as exc:
            _send_json(self, HTTPStatus.FORBIDDEN, {"error": str(exc), "code": "bad_passphrase"})
        except BadMagic as exc:
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": str(exc), "code": "bad_magic"})
        except UnsupportedVersion as exc:
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": str(exc), "code": "unsupported_version"})
        except BundleTooLarge as exc:
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": str(exc), "code": "too_large"})
        except ValueError as exc:
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": str(exc), "code": "invalid_passphrase"})
        except Exception as exc:  # noqa: BLE001
            _send_json(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

    def _handle_epic_oauth_callback(self) -> None:
        from urllib.parse import parse_qs, urlparse

        from shared.supabase_auth import auth_enabled

        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        code = (params.get("code") or [None])[0]
        state = (params.get("state") or [None])[0]
        require_state = auth_enabled()
        if require_state and not state:
            self.send_response(HTTPStatus.BAD_REQUEST)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            body = b"<html><body><p>Missing OAuth state.</p></body></html>"
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        profile_id = _consume_epic_oauth_state(state, require_state=require_state)
        if profile_id is None:
            self.send_response(HTTPStatus.BAD_REQUEST)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            body = b"<html><body><p>Invalid or expired OAuth state.</p></body></html>"
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        set_request_profile_id(profile_id)
        if not code:
            self.send_response(HTTPStatus.BAD_REQUEST)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            body = b"<html><body><p>Missing authorization code.</p></body></html>"
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        try:
            from auth.manager import mark_connected
            from epic_client import EpicClient, default_epic_cache_dir

            client = EpicClient(auth_code=code, cache_dir=default_epic_cache_dir())
            client.login()
            mark_connected("epic", {"EPIC_AUTH_CODE": code})
            body = (
                b"<html><body><p>Epic connected. You can close this tab and return to the dashboard.</p>"
                b"<script>try{const c=new BroadcastChannel('baklog-auth');"
                b"c.postMessage({provider:'epic'});c.close();}catch(e){}"
                b"setTimeout(()=>window.close(),1500)</script></body></html>"
            )
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:  # noqa: BLE001
            safe = html.escape(str(exc), quote=True)
            body = f"<html><body><p>Epic sign-in failed: {safe}</p></body></html>".encode()
            self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def _handle_auth_stream(self, session_id: str) -> None:
        global _sse_connections
        session_id = session_id.strip("/").split("/", 1)[0]
        try:
            from auth.manager import get_auth_session
        except ImportError as exc:
            _send_json(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
            return
        session = get_auth_session(session_id)
        if session is None:
            self.send_error(HTTPStatus.NOT_FOUND, "Unknown auth session")
            return

        with _sse_lock:
            if _sse_connections >= MAX_SSE_CONNECTIONS:
                _send_json(
                    self,
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {"error": f"too many stream connections (max {MAX_SSE_CONNECTIONS})"},
                )
                return
            _sse_connections += 1

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        try:
            while True:
                try:
                    event, data = session.events.get(timeout=30)
                    self._sse_write(event, data)
                    if event == "done":
                        return
                except queue.Empty:
                    self._sse_write_raw(b": keepalive\n\n")
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        finally:
            with _sse_lock:
                _sse_connections = max(0, _sse_connections - 1)

    def _handle_stream(self, run_id: str) -> None:
        global _sse_connections
        run_id = run_id.strip("/").split("/", 1)[0].split("?", 1)[0]
        since = _stream_resume_since(self)
        run = _run_accessible(MANAGER.get(run_id))
        if run is None:
            terminal = MANAGER.stream_terminal_summary(run_id)
            if terminal is not None:
                from shared.supabase_auth import auth_enabled
                if auth_enabled() and terminal.get("profile_id") != get_active_profile_id():
                    terminal = None
            if terminal is None:
                self.send_error(HTTPStatus.NOT_FOUND, "Unknown run id")
                return
            with _sse_lock:
                if _sse_connections >= MAX_SSE_CONNECTIONS:
                    _send_json(
                        self,
                        HTTPStatus.SERVICE_UNAVAILABLE,
                        {"error": f"too many stream connections (max {MAX_SSE_CONNECTIONS})"},
                    )
                    return
                _sse_connections += 1
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            try:
                self._sse_write(
                    "status",
                    {
                        "status": terminal.get("status"),
                        "started_at": terminal.get("started_at"),
                        "ended_at": terminal.get("ended_at"),
                        "exit_code": terminal.get("exit_code"),
                    },
                )
                self._sse_write(
                    "done",
                    {
                        "status": terminal.get("status"),
                        "exit_code": terminal.get("exit_code"),
                        "started_at": terminal.get("started_at"),
                        "ended_at": terminal.get("ended_at"),
                    },
                )
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                pass
            finally:
                with _sse_lock:
                    _sse_connections = max(0, _sse_connections - 1)
            return

        with _sse_lock:
            if _sse_connections >= MAX_SSE_CONNECTIONS:
                _send_json(
                    self,
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {"error": f"too many stream connections (max {MAX_SSE_CONNECTIONS})"},
                )
                return
            _sse_connections += 1

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        q, replay, already_done = run.attach_listener(since)
        try:
            self._sse_write("status", {
                "status": run.status,
                "started_at": run.started_at,
                "ended_at": run.ended_at,
                "exit_code": run.exit_code,
            })
            for msg in replay:
                self._sse_write("line", msg, event_id=msg.get("seq"))

            if already_done:
                self._sse_write("done", {
                    "status": run.status,
                    "exit_code": run.exit_code,
                    "started_at": run.started_at,
                    "ended_at": run.ended_at,
                })
                return

            last_ping = time.time()
            while True:
                try:
                    event, data = q.get(timeout=15)
                except queue.Empty:
                    self._sse_write_raw(b": keepalive\n\n")
                    last_ping = time.time()
                    continue
                event_id = data.get("seq") if event == "line" and isinstance(data, dict) else None
                self._sse_write(event, data, event_id=event_id)
                if event == "done":
                    return
                if time.time() - last_ping > 30:
                    self._sse_write_raw(b": keepalive\n\n")
                    last_ping = time.time()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            # Browser closed the SSE (tab switch, reload, navigate). Not an error.
            pass
        finally:
            run.detach_listener(q)
            with _sse_lock:
                _sse_connections = max(0, _sse_connections - 1)

    # ---- SSE helpers -------------------------------------------------------
    def _sse_write(self, event: str, data: Any, *, event_id: int | str | None = None) -> None:
        self._sse_write_raw(_sse_format(event, data, event_id=event_id))

    def _sse_write_raw(self, chunk: bytes) -> None:
        try:
            self.wfile.write(chunk)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            # Re-raise so _handle_stream's outer try/except can break the loop
            # and call detach_listener. Windows fires ConnectionAbortedError
            # (WinError 10053) instead of BrokenPipeError on client disconnect.
            raise

    # ---- small niceties ----------------------------------------------------
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - http.server API
        # Quieter logs; skip favicon and api keepalive noise.
        if "/api/stream/" in self.path:
            return
        super().log_message(format, *args)


def _shutdown_server() -> None:
    MANAGER.shutdown()


def _maybe_import_legacy_env() -> None:
    """One-time: migrate root .env credentials into the default profile's encrypted
    blob, then archive .env as .env.imported. Never blocks server start on failure."""
    env_path = ROOT / ".env"
    imported_path = ROOT / ".env.imported"
    if not env_path.is_file() or imported_path.exists():
        return
    try:
        from auth.manager import import_env_credentials
        from shared.profile_paths import DEFAULT_PROFILE_ID

        keys = import_env_credentials(profile_id=DEFAULT_PROFILE_ID)
        os.replace(env_path, imported_path)
        print(
            f"[auth] Imported {len(keys)} provider(s) from .env into profile "
            f"'{DEFAULT_PROFILE_ID}' -> .env.imported",
            flush=True,
        )
    except Exception as exc:  # noqa: BLE001 - migration must never block boot
        print(f"[auth] .env import skipped: {exc}", file=sys.stderr, flush=True)


def _dev_server_port_busy() -> bool:
    """True when something is already accepting TCP on HOST:PORT."""
    try:
        with socket.create_connection((HOST, PORT), timeout=0.3):
            return True
    except OSError:
        return False


def _exit_if_dev_server_busy() -> None:
    if _dev_server_port_busy():
        print(_DEV_SERVER_BUSY_MSG, file=sys.stderr, flush=True)
        raise SystemExit(1)


class BaklogDevServer(ThreadingHTTPServer):
    allow_reuse_address = False


def main() -> None:
    atexit.register(_shutdown_server)
    _maybe_import_legacy_env()

    def _handle_exit(signum: int, _frame: Any) -> None:
        print(f"\nShutting down (signal {signum}).")
        _shutdown_server()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, _handle_exit)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_exit)

    _exit_if_dev_server_busy()
    handler = partial(Handler, directory=str(ROOT))
    try:
        httpd = BaklogDevServer((HOST, PORT), handler)
    except OSError:
        print(_DEV_SERVER_BUSY_MSG, file=sys.stderr, flush=True)
        raise SystemExit(1) from None
    with httpd:
        print(f"BAKLOG dev server on http://{HOST}:{PORT}")
        print(f"Python for fetchers: {_python_executable()}")
        print(f"Registered fetchers: {len(FETCHERS)}")
        print(f"Run history: {RUN_HISTORY_FILE} (max {MAX_HISTORY})")
        if _SERVER_ENV_PROFILE_OVERRIDE:
            print(
                f"NOTE: BAKLOG_PROFILE={_SERVER_ENV_PROFILE_OVERRIDE!r} was set in the server "
                f"shell; ignoring it so the profile menu owns the active profile "
                f"(now {get_active_profile_id()!r}). Per-run fetchers still pin their own profile.",
                flush=True,
            )
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down.")


if __name__ == "__main__":
    main()
