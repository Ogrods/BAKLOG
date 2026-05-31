"""Local dev server for the Steam Backlog dashboard.

Serves static files like ``python -m http.server`` and adds a tiny API that
lets dashboard chips trigger Python fetchers and stream their output back to
the browser via Server-Sent Events. Also owns the user's personal data
(statuses, notes, priorities, prefs, manually-added games) so it survives
browser changes, port changes, and cache wipes.

Endpoints:
    GET  /api/runs                 -> {active, queue, history}
    POST /api/run/<key>            -> {run_id, status}    (queues a fetcher)
    POST /api/run/<run_id>/cancel  -> cancel queued or running fetcher
    GET  /api/stream/<run_id>      -> SSE: line / done / error events
    GET  /api/personal        -> {personal, prefs, manual, updated_at}
    PUT  /api/personal        -> overwrite the whole document atomically
    GET  /api/auth/status     -> per-provider connection state
    POST /api/auth/<p>/start  -> begin Playwright sign-in (returns session_id)
    GET  /api/auth/<id>/stream -> SSE auth flow events
    PUT  /api/auth/<p>/credentials -> save form API keys
    POST /api/auth/<p>/disconnect  -> wipe stored credentials
    GET  /oauth/epic/callback -> Epic OAuth redirect handler

Bind: 127.0.0.1 only. The fetcher whitelist is loaded from fetchers/manifest.json
so the browser cannot execute arbitrary commands.
"""
from __future__ import annotations

import atexit
import json
import os
import queue
import signal
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

ROOT = Path(__file__).resolve().parent

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass

HOST = "127.0.0.1"
PORT = int(os.environ.get("PORT", "8765"))
MAX_HISTORY = 200
MAX_LINES_PER_RUN = 25_000
MAX_SSE_CONNECTIONS = 8
STALL_FIRST_NOTICE_SEC = 30
STALL_REPEAT_SEC = 60
STALL_POLL_SEC = 1.0
RUNS_DIR = ROOT / "cache" / "runs"
ACTIVE_RUNS_FILE = RUNS_DIR / "active.json"
RUN_HISTORY_FILE = RUNS_DIR / "history.json"

_sse_connections = 0
_sse_lock = threading.Lock()

# Personal-data persistence.
# This file is the source of truth for the user's edits. localStorage in the
# browser is treated as a hydration cache that is overwritten from this file
# on every boot.
PERSONAL_DIR = ROOT / "data"
PERSONAL_FILE = PERSONAL_DIR / "personal.json"
PERSONAL_BACKUP_DIR = PERSONAL_DIR / "personal_backups"
PERSONAL_BACKUP_KEEP = 10
PERSONAL_MAX_BYTES = 32 * 1024 * 1024  # 32 MB hard cap on the PUT body
_personal_lock = threading.RLock()
_personal_last_backup_at = 0.0


def _empty_personal_doc() -> dict[str, Any]:
    return {
        "personal": {},
        "prefs": {},
        "manual": [],
        "updated_at": None,
        "schema_version": 1,
    }


def _load_personal_doc() -> dict[str, Any]:
    with _personal_lock:
        if not PERSONAL_FILE.exists():
            return _empty_personal_doc()
        try:
            with PERSONAL_FILE.open("r", encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[personal] corrupted: {exc!r} -- returning empty doc", file=sys.stderr)
            return _empty_personal_doc()
        # Defensive defaults so the client can rely on shape.
        doc.setdefault("personal", {})
        doc.setdefault("prefs", {})
        doc.setdefault("manual", [])
        doc.setdefault("updated_at", None)
        doc.setdefault("schema_version", 1)
        return doc


def _validate_personal_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    personal = payload.get("personal", {})
    prefs = payload.get("prefs", {})
    manual = payload.get("manual", [])
    if not isinstance(personal, dict):
        raise ValueError("personal must be an object")
    if not isinstance(prefs, dict):
        raise ValueError("prefs must be an object")
    if not isinstance(manual, list):
        raise ValueError("manual must be an array")
    return {"personal": personal, "prefs": prefs, "manual": manual}


def _rotate_personal_backup() -> None:
    """Keep a rolling set of timestamped backups so a bad save can't wipe
    out months of edits. Runs at most once every 5 minutes; the previous
    on-disk file becomes the backup before being overwritten."""
    global _personal_last_backup_at
    now = time.time()
    if now - _personal_last_backup_at < 300:
        return
    if not PERSONAL_FILE.exists():
        return
    PERSONAL_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
    backup = PERSONAL_BACKUP_DIR / f"personal-{stamp}.json"
    try:
        backup.write_bytes(PERSONAL_FILE.read_bytes())
    except OSError as exc:
        print(f"[personal] backup failed: {exc!r}", file=sys.stderr)
        return
    _personal_last_backup_at = now
    # Prune oldest backups beyond the keep-count.
    backups = sorted(PERSONAL_BACKUP_DIR.glob("personal-*.json"))
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
        PERSONAL_DIR.mkdir(parents=True, exist_ok=True)
        _rotate_personal_backup()
        tmp = PERSONAL_FILE.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        os.replace(tmp, PERSONAL_FILE)
        return doc


# A fetcher is just a label plus an argv. argv is fixed at definition time;
# nothing the browser sends affects which command runs.
def _argv(*parts: str) -> list[str]:
    return [_python_executable(), *parts]


def _python_executable() -> str:
    """Prefer the project's venv interpreter when present."""
    candidates = [
        ROOT / ".venv" / "Scripts" / "python.exe",  # Windows
        ROOT / ".venv" / "bin" / "python",          # POSIX
        ROOT / ".venv" / "bin" / "python3",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return sys.executable


MANIFEST_FILE = ROOT / "fetchers" / "manifest.json"


def _load_fetchers() -> dict[str, dict[str, Any]]:
    """Build the fetcher registry from fetchers/manifest.json."""
    try:
        raw = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
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
        fetchers[key] = {
            "label": label,
            "argv": _argv(script, *map(str, extra_args)),
            "refreshArgs": [str(a) for a in refresh_args],
            "metaKey": entry.get("metaKey", key),
            "group": entry.get("group", "library"),
            "color": entry.get("color"),
            "requires": requires,
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
        val = resolve(env_name) if resolve else os.getenv(env_name, "").strip()
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
    data = _read_json_file(ACTIVE_RUNS_FILE, {"runs": []})
    runs = data.get("runs") if isinstance(data, dict) else []
    return runs if isinstance(runs, list) else []


def _write_active_runs(runs: list[dict[str, Any]]) -> None:
    _write_json_atomic(ACTIVE_RUNS_FILE, {"runs": runs})


def _load_run_history() -> list[dict[str, Any]]:
    data = _read_json_file(RUN_HISTORY_FILE, [])
    return data if isinstance(data, list) else []


def _save_run_history(entries: list[dict[str, Any]]) -> None:
    _write_json_atomic(RUN_HISTORY_FILE, entries[:MAX_HISTORY])


class Run:
    """A single queued/running/completed fetcher invocation."""

    __slots__ = (
        "id", "key", "label", "status", "started_at", "ended_at", "exit_code",
        "lines", "_lock", "_listeners", "_finished", "_proc", "cancelled", "refresh",
        "_log_path", "_runs_dir",
    )

    def __init__(self, key: str, refresh: bool = False, *, runs_dir: Path = RUNS_DIR) -> None:
        spec = FETCHERS[key]
        self.id: str = uuid.uuid4().hex[:12]
        self.key: str = key
        self.label: str = spec["label"]
        self.refresh: bool = refresh
        self.status: str = "queued"  # queued | running | done | failed | cancelled
        self.started_at: float | None = None
        self.ended_at: float | None = None
        self.exit_code: int | None = None
        self.cancelled: bool = False
        self._proc: subprocess.Popen[str] | None = None
        self._runs_dir = runs_dir
        self._runs_dir.mkdir(parents=True, exist_ok=True)
        self._log_path = self._runs_dir / f"{self.id}.jsonl"
        # Ring buffer for live listeners; full log is on disk for replay.
        self.lines: deque[dict[str, Any]] = deque(maxlen=MAX_LINES_PER_RUN)
        self._lock = threading.Lock()
        self._listeners: set[queue.Queue] = set()
        self._finished = threading.Event()

    def to_summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "key": self.key,
            "label": self.label,
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "exit_code": self.exit_code,
            "line_count": len(self.lines),
        }

    def add_line(self, stream: str, text: str) -> None:
        msg = {"t": time.time(), "stream": stream, "text": text}
        with self._lock:
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

    def replay_lines(self) -> list[dict[str, Any]]:
        if self._log_path.exists():
            replay: list[dict[str, Any]] = []
            try:
                with self._log_path.open(encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        replay.append(json.loads(line))
                return replay
            except (OSError, json.JSONDecodeError) as exc:
                print(f"[runs] log read failed {self.id}: {exc!r}", file=sys.stderr)
        with self._lock:
            return list(self.lines)

    def attach_listener(self) -> tuple[queue.Queue, list[dict[str, Any]], bool]:
        """Return (queue, replay-buffer, already-finished)."""
        q: queue.Queue = queue.Queue(maxsize=1024)
        with self._lock:
            replay = self.replay_lines()
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

    def cancel(self) -> bool:
        proc = None
        notify_done = False
        with self._lock:
            if self.status in ("done", "failed", "cancelled") or self._finished.is_set():
                return False
            if self.status == "queued":
                self.status = "cancelled"
                self.exit_code = -1
                self.ended_at = time.time()
                notify_done = True
            elif self.status == "running":
                self.cancelled = True
                proc = self._proc
            else:
                return False
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
            return True
        if proc is not None and proc.poll() is None:
            proc.terminate()
        return True


class RunManager:
    """Single-worker queue. Fetchers may share locks (PSN session, etc.) so
    we deliberately serialize them rather than spawn in parallel."""

    def __init__(self, runs_dir: Path | None = None) -> None:
        self._runs_dir = runs_dir or RUNS_DIR
        self._runs_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._queue: queue.Queue[Run] = queue.Queue()
        self._pending: list[Run] = []  # queued + active, in submission order
        self._history: deque[dict[str, Any]] = deque(
            _load_run_history()[-MAX_HISTORY:],
            maxlen=MAX_HISTORY,
        )
        self._active: Run | None = None
        self._runs_by_id: dict[str, Run] = {}
        self._reap_orphan_processes()
        threading.Thread(target=self._worker_loop, name="run-worker", daemon=True).start()

    def _append_history(self, summary: dict[str, Any]) -> None:
        with self._lock:
            self._history.appendleft(summary)
            _save_run_history(list(self._history))

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
            self._append_history(summary)
        _write_active_runs([])

    def shutdown(self) -> None:
        with self._lock:
            pending = list(self._pending)
            active = self._active
        for run in pending:
            run.cancel()
        if active is not None:
            active.cancel()
            proc = active._proc
            if proc is not None and proc.poll() is None:
                try:
                    proc.terminate()
                except OSError:
                    pass
        _write_active_runs([])

    def submit(self, key: str, *, refresh: bool = False) -> Run:
        if key not in FETCHERS:
            raise KeyError(key)
        with self._lock:
            if any(r.key == key and r.status in ("queued", "running") for r in self._pending):
                raise ValueError(f"{key} already queued or running")
        run = Run(key, refresh=refresh, runs_dir=self._runs_dir)
        with self._lock:
            self._pending.append(run)
            self._runs_by_id[run.id] = run
        self._queue.put(run)
        return run

    def cancel(self, run_id: str) -> tuple[Run | None, str | None]:
        with self._lock:
            run = self._runs_by_id.get(run_id)
            if run is None:
                return None, "not_found"
            if run.status in ("done", "failed", "cancelled") or run._finished.is_set():
                return None, "already_finished"
        if not run.cancel():
            return None, "already_finished"
        with self._lock:
            if run in self._pending:
                self._pending.remove(run)
        return run, None

    def get(self, run_id: str) -> Run | None:
        with self._lock:
            return self._runs_by_id.get(run_id)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            active = self._active.to_summary() if self._active else None
            queued = [r.to_summary() for r in self._pending if r.status == "queued"]
            history = list(self._history)
        return {"active": active, "queue": queued, "history": history}

    def _finalize_run(self, run: Run) -> None:
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
        self._append_history(run.to_summary())

    def _worker_loop(self) -> None:
        while True:
            run = self._queue.get()
            if not run._finished.is_set():
                with self._lock:
                    self._active = run
                try:
                    if run.status != "cancelled":
                        self._execute(run)
                except Exception as exc:  # noqa: BLE001 - surface anything the subprocess plumbing might raise.
                    if not run.cancelled:
                        run.status = "failed"
                        run.exit_code = -1
                        run.add_line("stderr", f"[server] worker error: {exc!r}")
            self._finalize_run(run)

    def _execute(self, run: Run) -> None:
        argv = run.argv()
        run.status = "running"
        run.started_at = time.time()
        run.broadcast("status", {"status": run.status, "started_at": run.started_at})
        run.add_line("stdout", f"$ {' '.join(argv)}")

        env = os.environ.copy()
        # Force unbuffered Python output so we see progress in real time.
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"

        try:
            proc = subprocess.Popen(  # noqa: S603 - argv is fixed in FETCHERS, not user input
                argv,
                cwd=str(ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
            )
        except FileNotFoundError as exc:
            run.status = "failed"
            run.exit_code = -1
            run.add_line("stderr", f"[server] cannot launch: {exc}")
            return

        run._proc = proc
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
                silent = now - last_line_at
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

        proc.wait()
        run.exit_code = proc.returncode
        if run.cancelled:
            run.status = "cancelled"
            run.add_line("stderr", "[server] cancelled")
        elif proc.returncode == 0:
            run.status = "done"
        else:
            run.status = "failed"
        run._proc = None


MANAGER = RunManager()


def _send_json(handler: SimpleHTTPRequestHandler, status: int, payload: Any) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def _sse_format(event: str, data: Any) -> bytes:
    payload = data if isinstance(data, str) else json.dumps(data)
    out = f"event: {event}\ndata: {payload}\n\n"
    return out.encode("utf-8")


class Handler(SimpleHTTPRequestHandler):
    server_version = "SteamBacklogDev/1.0"

    # ---- routing -----------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802 - http.server API
        if self.path == "/api/runs":
            self._handle_runs()
            return
        if self.path == "/api/fetchers":
            self._handle_fetchers()
            return
        if self.path == "/api/personal":
            self._handle_personal_get()
            return
        if self.path == "/api/auth/status":
            self._handle_auth_status()
            return
        if self.path.startswith("/api/auth/") and self.path.endswith("/stream"):
            rest = self.path[len("/api/auth/") : -len("/stream")].strip("/")
            self._handle_auth_stream(rest)
            return
        if self.path.startswith("/oauth/epic/callback"):
            self._handle_epic_oauth_callback()
            return
        if self.path.startswith("/api/stream/"):
            self._handle_stream(self.path[len("/api/stream/"):])
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        if self.path.startswith("/api/run/"):
            rest = self.path[len("/api/run/"):].strip("/")
            if rest.endswith("/cancel"):
                run_id = rest[: -len("/cancel")].strip("/")
                self._handle_cancel(run_id)
            else:
                self._handle_submit(rest)
            return
        if self.path.startswith("/api/auth/") and self.path.endswith("/start"):
            provider = self.path[len("/api/auth/") : -len("/start")].strip("/")
            self._handle_auth_start(provider)
            return
        if self.path.startswith("/api/auth/") and self.path.endswith("/open-url"):
            provider = self.path[len("/api/auth/") : -len("/open-url")].strip("/")
            self._handle_auth_open_url(provider)
            return
        if self.path.startswith("/api/auth/") and self.path.endswith("/disconnect"):
            provider = self.path[len("/api/auth/") : -len("/disconnect")].strip("/")
            self._handle_auth_disconnect(provider)
            return
        if self.path == "/api/auth/master-password":
            self._handle_auth_master_password()
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")

    def do_PUT(self) -> None:  # noqa: N802 - http.server API
        if self.path == "/api/personal":
            self._handle_personal_put()
            return
        if self.path.startswith("/api/auth/") and self.path.endswith("/credentials"):
            provider = self.path[len("/api/auth/") : -len("/credentials")].strip("/")
            self._handle_auth_credentials(provider)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")

    # ---- handlers ----------------------------------------------------------
    def _handle_fetchers(self) -> None:
        try:
            from dotenv import load_dotenv

            load_dotenv(ROOT / ".env", override=True)
        except ImportError:
            pass
        data = {
            "fetchers": [
                {
                    "key": k,
                    "label": v["label"],
                    "cmd": " ".join(v["argv"][1:]),
                    "metaKey": v.get("metaKey", k),
                    "group": v.get("group", "library"),
                    "color": v.get("color"),
                    "requires": v.get("requires") or [],
                    "missing_requirements": _missing_requirements(v.get("requires") or []),
                    "supports_refresh": bool(v.get("refreshArgs")),
                }
                for k, v in FETCHERS.items()
            ]
        }
        _send_json(self, HTTPStatus.OK, data)

    @staticmethod
    def _parse_run_submit_path(rest: str) -> tuple[str, bool]:
        from urllib.parse import parse_qs

        path, _, qs = rest.partition("?")
        key = path.strip("/").split("/", 1)[0]
        params = parse_qs(qs) if qs else {}
        refresh_val = (params.get("refresh") or ["0"])[0].lower()
        refresh = refresh_val in ("1", "true", "yes")
        return key, refresh

    def _handle_personal_get(self) -> None:
        try:
            doc = _load_personal_doc()
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
            _send_json(self, HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": f"body too large ({length} > {PERSONAL_MAX_BYTES})"})
            return
        try:
            raw = self.rfile.read(length).decode("utf-8")
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": f"invalid JSON: {exc!r}"})
            return
        try:
            doc = _save_personal_doc(payload)
        except ValueError as exc:
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        except OSError as exc:
            _send_json(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"write failed: {exc!r}"})
            return
        _send_json(self, HTTPStatus.OK, doc)

    def _handle_runs(self) -> None:
        _send_json(self, HTTPStatus.OK, MANAGER.snapshot())

    def _handle_submit(self, rest: str) -> None:
        key, refresh = self._parse_run_submit_path(rest)
        if key not in FETCHERS:
            _send_json(self, HTTPStatus.NOT_FOUND, {"error": f"unknown fetcher: {key}"})
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
        run, err = MANAGER.cancel(run_id)
        if err == "not_found":
            _send_json(self, HTTPStatus.NOT_FOUND, {"error": f"unknown run: {run_id}"})
            return
        if err == "already_finished":
            _send_json(self, HTTPStatus.CONFLICT, {"error": "run already finished"})
            return
        assert run is not None
        _send_json(self, HTTPStatus.OK, run.to_summary())

    def _handle_auth_status(self) -> None:
        try:
            from auth.manager import get_status

            _send_json(self, HTTPStatus.OK, {"providers": get_status()})
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

            session_id = start_browser_auth(provider)
            _send_json(self, HTTPStatus.ACCEPTED, {"session_id": session_id, "provider": provider})
        except KeyError:
            _send_json(self, HTTPStatus.NOT_FOUND, {"error": f"unknown provider: {provider}"})
        except ValueError as exc:
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
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

    def _handle_epic_oauth_callback(self) -> None:
        from urllib.parse import parse_qs, urlparse

        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        code = (params.get("code") or [None])[0]
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
            from epic_client import EpicClient

            client = EpicClient(auth_code=code)
            client.login()
            mark_connected("epic", {"EPIC_AUTH_CODE": code})
            body = (
                b"<html><body><p>Epic connected. You can close this tab and return to the dashboard.</p>"
                b"<script>setTimeout(()=>window.close(),1500)</script></body></html>"
            )
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:  # noqa: BLE001
            body = f"<html><body><p>Epic sign-in failed: {exc}</p></body></html>".encode("utf-8")
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
        run_id = run_id.strip("/").split("/", 1)[0]
        run = MANAGER.get(run_id)
        if run is None:
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

        q, replay, already_done = run.attach_listener()
        try:
            self._sse_write("status", {
                "status": run.status,
                "started_at": run.started_at,
                "ended_at": run.ended_at,
                "exit_code": run.exit_code,
            })
            for msg in replay:
                self._sse_write("line", msg)

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
                self._sse_write(event, data)
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
    def _sse_write(self, event: str, data: Any) -> None:
        self._sse_write_raw(_sse_format(event, data))

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


def main() -> None:
    atexit.register(_shutdown_server)

    def _handle_exit(signum: int, _frame: Any) -> None:
        print(f"\nShutting down (signal {signum}).")
        _shutdown_server()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, _handle_exit)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_exit)

    handler = partial(Handler, directory=str(ROOT))
    with ThreadingHTTPServer((HOST, PORT), handler) as httpd:
        print(f"Steam Backlog dev server on http://{HOST}:{PORT}")
        print(f"Python for fetchers: {_python_executable()}")
        print(f"Registered fetchers: {len(FETCHERS)}")
        print(f"Run history: {RUN_HISTORY_FILE} (max {MAX_HISTORY})")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down.")


if __name__ == "__main__":
    main()
