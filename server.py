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
    POST /api/runs/cancel          -> cancel in-flight runs; ?lane=fetcher|internal scopes a lane, ?force=1 resets
    GET  /api/stream/<run_id>      -> SSE: status / line / done events (?since=N or Last-Event-ID for resume)
    GET  /api/personal        -> {personal, prefs, manual, updated_at}
    PUT  /api/personal        -> overwrite the whole document atomically
    POST /api/catalogs/import -> restore games_*.json / itad_prices.json from backup
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
import json
import os
import queue
import secrets
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
from urllib.parse import parse_qs, urlparse

from shared.built_frontend import (
    is_immutable_built_asset as _is_immutable_built_asset,
)
from shared.built_frontend import (
    maybe_serve_built_index as _maybe_serve_built_index,
)
from shared.dev_server_pids import (
    pid_alive as _pid_alive,
)
from shared.dev_server_pids import (
    reclaim_or_exit as _reclaim_or_exit,
)
from shared.dev_server_pids import (
    remove_own_pid_file as _remove_own_pid_file,
)
from shared.dev_server_pids import (
    terminate_pid as _terminate_pid,
)
from shared.dev_server_pids import (
    write_pid_file as _write_pid_file_impl,
)
from shared.idle_watchdog import (
    note_activity as _note_activity,
)
from shared.idle_watchdog import (
    start_idle_watchdog as _start_idle_watchdog,
)
from shared.install_paths import (
    bundle_root,
    data_root,
    is_frozen,
    load_built_manifest,
    serve_built_frontend,
    static_root,
)

if __name__ == "__main__":
    from baklog_fetcher_dispatch import exit_if_fetcher_child

    exit_if_fetcher_child()


def _warn_built_manifest_version_mismatch() -> None:
    if not serve_built_frontend():
        return
    manifest = load_built_manifest()
    built_ver = str(manifest.get("version") or "").strip()
    app_ver = _app_version()
    if built_ver and built_ver != app_ver:
        print(
            f"WARNING: dist/manifest.json version {built_ver} != app {app_ver} "
            f"— run npm run build before testing packaged frontend",
            flush=True,
        )

ROOT = data_root()

try:
    from shared.bundled_auth_env import bootstrap_server_env

    bootstrap_server_env(ROOT)
except ImportError:
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:
        pass

HOST = "127.0.0.1"
PORT = int(os.environ.get("PORT", "8765"))
ADMIN_ENABLED = os.environ.get("BAKLOG_ADMIN") == "1"
FREE_CLAIMS_INPUT_PATH = Path(
    os.environ.get("BAKLOG_FREE_CLAIMS_INPUT", "free-claims.input.json")
)
FREE_CLAIMS_AUTO_PATH = Path("curated/free_claims.auto.json")
FREE_CLAIMS_APPROVED_PATH = Path("curated/free_claims.approved.json")
FREE_CLAIMS_BUILT_PATH = Path("landing/free-claims.json")
SPONSORS_PATH = Path(os.environ.get("BAKLOG_SPONSORS_INPUT", "curated/sponsors.json"))
INTERNAL_JOBS_OVERLAY = bundle_root() / "admin" / "admin-jobs.json"
MAX_ADMIN_CLAIM_ITEMS = int(os.environ.get("BAKLOG_MAX_ADMIN_CLAIM_ITEMS", "500"))
MAX_ADMIN_ENRICH_BATCH = int(os.environ.get("BAKLOG_MAX_ADMIN_ENRICH_BATCH", "64"))
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


# Statuses that occupy a queue slot (cap = 1: one active run only; no queuing).
_IN_FLIGHT_STATUSES = frozenset({"queued", "launching", "running", "cancelling"})

_sse_connections = 0
_sse_lock = threading.Lock()

_BAKLOG_LOCAL_HEADER = "X-BAKLOG-Local"
# Canonical (unbracketed, port-stripped) loopback hostnames. IPv6 is stored as
# bare "::1" because urlparse().hostname returns it without brackets; the Host
# header path strips brackets/port via _normalize_host before comparing.
_LOCAL_HOSTNAMES = frozenset({"127.0.0.1", "localhost", "::1"})
from shared.log_redact import (  # noqa: E402, I001
    redact_diagnostics_payload as _redact_diagnostics_payload,
    redact_log_line as _redact_log_line,
)
from shared.server_epic_oauth import (  # noqa: E402, I001
    register_epic_oauth_state as _register_epic_oauth_state,
)
from shared.server_stream_tickets import (  # noqa: E402, I001
    STREAM_ATTACH_LONG_WAIT_SEC as _STREAM_ATTACH_LONG_WAIT_SEC,
    STREAM_ATTACH_POLL_SEC as _STREAM_ATTACH_POLL_SEC,
    STREAM_ATTACH_SHORT_WAIT_SEC as _STREAM_ATTACH_SHORT_WAIT_SEC,
    commit_stream_ticket as _commit_stream_ticket,
    consume_stream_ticket as _consume_stream_ticket,
    mint_stream_ticket as _mint_stream_ticket,
    peek_stream_ticket as _peek_stream_ticket,
    stream_ticket_from_handler as _stream_ticket_from_handler,
)


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
from shared import server_internal_routes  # noqa: E402
from shared.platform_support import platform_supported  # noqa: E402
from shared.profile_paths import (  # noqa: E402
    PROFILE_CACHE_JSON_FILES,
    cache_json_path,
    catalog_path,
    clear_request_profile_id,
    free_claims_path,
    get_active_profile_id,
    personal_backup_dir,
    personal_dir,
    personal_path,
    profile_root,
    runs_dir,
    set_request_profile_id,
    sponsors_path,
)
from shared.server_static import (  # noqa: E402
    LIBRARY_JSON_RE as _LIBRARY_JSON_RE,
)
from shared.server_static import (  # noqa: E402
    normalize_static_path as _normalize_static_path,
)
from shared.server_static import (  # noqa: E402
    resolved_static_path_allowed as _resolved_static_path_allowed,
)
from shared.server_static import (  # noqa: E402
    static_class as _static_class_impl,
)
from shared.subprocess_guard import _max_run_seconds_from_env, popen_fetcher  # noqa: E402

MAX_RUN_SECONDS = _max_run_seconds_from_env()


def _max_run_seconds_for_key(key: str) -> float:
    """Per-fetcher runtime cap from manifest maxRunSeconds, else global default.

    maxRunSeconds <= 0 means "no cap" (returns inf) for long enrichers like HLTB.
    """
    spec = FETCHERS.get(key) or INTERNAL_JOBS.get(key) or {}
    override = spec.get("maxRunSeconds")
    try:
        value = float(override) if override is not None else None
    except (TypeError, ValueError):
        value = None
    if value is None:
        return MAX_RUN_SECONDS
    return float("inf") if value <= 0 else max(60.0, value)


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

# Kept for tests that monkeypatch this name.
PERSONAL_BACKUP_DIR = personal_backup_dir()


def _refresh_personal_paths() -> None:
    """Rebind module-level personal + run paths after profile switch (tests may patch)."""
    global PERSONAL_BACKUP_DIR
    global RUNS_DIR, ACTIVE_RUNS_FILE, RUN_HISTORY_FILE, QUEUE_FILE
    PERSONAL_BACKUP_DIR = personal_backup_dir()
    RUNS_DIR = runs_dir()
    ACTIVE_RUNS_FILE = RUNS_DIR / "active.json"
    RUN_HISTORY_FILE = RUNS_DIR / "history.json"
    QUEUE_FILE = RUNS_DIR / "queue.json"
    MANAGER.rebind_profile_paths()
    # The decrypted secrets cache is keyed to the previous profile — drop it so the
    # next load re-derives the new profile's HKDF subkey from its own secrets.bin.
    try:
        import auth.secrets as _secrets

        _secrets.reset_cache()
    except Exception:  # noqa: BLE001 - cache reset is best-effort
        pass
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


class PersonalEmptyOverwriteError(RuntimeError):
    """Refusing to replace a populated personal doc with a fully empty payload."""


_BAKLOG_ALLOW_EMPTY_HEADER = "X-BAKLOG-Allow-Empty"


def _personal_doc_is_meaningful(doc: dict[str, Any]) -> bool:
    """True when the stored doc carries personal edits, manual games, or first-seen stamps."""
    personal = doc.get("personal")
    if isinstance(personal, dict):
        if any(k != "__migrated_v3" for k in personal):
            return True
    manual = doc.get("manual")
    if isinstance(manual, list) and manual:
        return True
    library_first_seen = doc.get("libraryFirstSeen")
    if isinstance(library_first_seen, dict) and library_first_seen:
        return True
    return False


def _personal_payload_is_empty(validated: dict[str, Any]) -> bool:
    """True when the incoming payload has no personal/manual/first-seen data."""
    personal = validated.get("personal") or {}
    if not isinstance(personal, dict):
        return True
    if any(k != "__migrated_v3" for k in personal):
        return False
    manual = validated.get("manual") or []
    if isinstance(manual, list) and manual:
        return False
    library_first_seen = validated.get("libraryFirstSeen") or {}
    if isinstance(library_first_seen, dict) and library_first_seen:
        return False
    return True


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


def _save_personal_doc(payload: dict[str, Any], *, allow_empty: bool = False) -> dict[str, Any]:
    """Atomic write: temp file + os.replace(). Never partial; never corrupted."""
    with _personal_lock:
        validated = _validate_personal_payload(payload)
        if not allow_empty and _personal_payload_is_empty(validated):
            existing = _load_personal_doc()
            if _personal_doc_is_meaningful(existing):
                path = personal_path()
                print(
                    f"[personal] refusing empty overwrite of populated doc at {path}",
                    file=sys.stderr,
                    flush=True,
                )
                raise PersonalEmptyOverwriteError("refusing empty overwrite")
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


def _fetcher_argv(key: str, script: str, extra_args: list) -> list[str]:
    if is_frozen():
        return _argv("--run-fetcher", key, *map(str, extra_args))
    return _argv(str(bundle_root() / script), *map(str, extra_args))


def _fetcher_cmd_label(argv: list[str]) -> str:
    if len(argv) > 2 and argv[1] == "--run-fetcher":
        return " ".join([argv[2], *argv[3:]])
    if len(argv) > 1:
        return " ".join([Path(argv[1]).name, *argv[2:]])
    return ""


def _python_executable() -> str:
    """Prefer the project's venv interpreter when present."""
    if is_frozen():
        return sys.executable
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


def _load_fetchers() -> dict[str, dict[str, Any]]:
    """Build the fetcher registry from fetchers/manifest.json."""
    try:
        from fetchers.registry import MANIFEST_PATH
    except ImportError as exc:
        print(f"[fetchers] registry import failed: {exc!r}", file=sys.stderr)
        return {}
    # Validation is a dev/CI integrity check that inspects fetcher source files;
    # keep it isolated so a validation hiccup (e.g. source not shipped in a frozen
    # build) can never blank the runtime registry.
    try:
        from fetchers.registry import validate_manifest

        for err in validate_manifest(MANIFEST_PATH):
            print(f"[fetchers] manifest: {err}", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001 - never let validation kill the registry
        print(f"[fetchers] manifest validation skipped: {exc!r}", file=sys.stderr)
    try:
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
        max_run_seconds = entry.get("maxRunSeconds")
        if max_run_seconds is not None:
            try:
                max_run_seconds = float(max_run_seconds)
            except (TypeError, ValueError):
                max_run_seconds = None
            else:
                # <= 0 = "no cap" sentinel (kept verbatim); else 60s floor.
                if max_run_seconds > 0:
                    max_run_seconds = max(60.0, max_run_seconds)
        fetchers[key] = {
            "label": label,
            # Absolute script path so the launch never depends on subprocess cwd.
            "argv": _fetcher_argv(key, script, extra_args),
            "refreshArgs": [str(a) for a in refresh_args],
            "metaKey": entry.get("metaKey", key),
            "group": entry.get("group", "library"),
            "color": entry.get("color"),
            "requires": requires,
            "platforms": [str(p) for p in platforms],
            "maxRunSeconds": max_run_seconds,
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

_DEFAULT_INTERNAL_JOBS: dict[str, dict[str, Any]] = {
    "claimSources": {
        "label": "Fetch claim sources",
        "script": "fetchers/fetch_claim_sources.py",
        "group": "claims",
        "description": "Auto-discover free claims from Epic, GamerPower, and ITAD giveaways RSS",
        "args": [],
        "options": {
            "--dry-run": {"type": "bool", "default": False},
            "--source": {
                "type": "enum",
                "values": ["all", "epic", "gamerpower", "itad"],
                "default": "all",
            },
        },
    },
    "buildClaims": {
        "label": "Build free claims feed",
        "script": "fetchers/build_free_claims.py",
        "group": "claims",
        "description": "Merge manual + approved auto items, enrich with Steam metadata, publish feed",
        "args": [],
        "options": {
            "--dry-run": {"type": "bool", "default": False},
            "--no-profile": {"type": "bool", "default": False},
            "--allow-empty": {"type": "bool", "default": False},
            "--require-manual-approval": {
                "type": "bool",
                "default": False,
            },
        },
    },
}


def _script_under_bundle(script: str) -> bool:
    """True when script resolves to a .py file under bundle_root (no path escape)."""
    rel = str(script or "").strip().replace("\\", "/").lstrip("/")
    if not rel or ".." in rel.split("/") or not rel.endswith(".py"):
        return False
    root = bundle_root().resolve()
    try:
        target = (root / rel).resolve()
        target.relative_to(root)
        return target.is_file()
    except (OSError, ValueError):
        return False


def _normalize_internal_job_entry(raw: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    key = str(raw.get("key") or "").strip()
    script = str(raw.get("script") or "").strip()
    if not key or not script or not _script_under_bundle(script):
        return None
    args = raw.get("args") or []
    if not isinstance(args, list):
        args = []
    options = raw.get("options") or {}
    if not isinstance(options, dict):
        options = {}
    return key, {
        "label": str(raw.get("label") or key),
        "script": script,
        "group": str(raw.get("group") or "internal"),
        "description": str(raw.get("description") or ""),
        "args": [str(a) for a in args],
        "options": options,
    }


def _load_internal_jobs() -> dict[str, dict[str, Any]]:
    jobs = {k: dict(v) for k, v in _DEFAULT_INTERNAL_JOBS.items()}
    if INTERNAL_JOBS_OVERLAY.is_file():
        try:
            overlay = json.loads(INTERNAL_JOBS_OVERLAY.read_text(encoding="utf-8"))
            for raw in overlay.get("jobs") or []:
                if not isinstance(raw, dict):
                    continue
                normalized = _normalize_internal_job_entry(raw)
                if not normalized:
                    continue
                key, entry = normalized
                if key in FETCHERS:
                    print(
                        f"[internal] skipping job {key}: collides with fetcher key",
                        file=sys.stderr,
                    )
                    continue
                jobs[key] = entry
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[internal] admin-jobs.json load failed: {exc!r}", file=sys.stderr)
    for key in list(jobs):
        if key in FETCHERS:
            print(
                f"[internal] built-in job {key} collides with fetcher key — omitting",
                file=sys.stderr,
            )
            del jobs[key]
    return jobs


def _internal_job_argv(spec: dict[str, Any], extra_args: list[str]) -> list[str]:
    base = spec.get("args") or []
    script = str(spec.get("script") or "").strip()
    if not _script_under_bundle(script):
        raise ValueError(f"invalid internal job script: {script!r}")
    return _argv(str(bundle_root() / script), *base, *extra_args)


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value in (1, "1", "true", "True", "yes", "on"):
        return True
    if value in (0, "0", "false", "False", "no", "off", None, ""):
        return False
    raise ValueError(f"invalid boolean value: {value!r}")


def validate_internal_args(spec: dict[str, Any], args: dict[str, Any]) -> list[str]:
    """Convert validated {flag: value} dict to argv tokens."""
    options = spec.get("options") or {}
    extra: list[str] = []
    for flag, value in args.items():
        if flag not in options:
            raise ValueError(f"unknown option: {flag}")
        opt = options[flag]
        opt_type = opt.get("type")
        if opt_type == "bool":
            if _coerce_bool(value):
                extra.append(flag)
        elif opt_type == "enum":
            val = str(value if value is not None else opt.get("default", ""))
            allowed = opt.get("values") or []
            if val not in allowed:
                raise ValueError(f"invalid value for {flag}: {val!r}")
            default = str(opt.get("default", ""))
            if val != default:
                extra.extend([flag, val])
        else:
            raise ValueError(f"unsupported option type for {flag}")
    return extra


def _resolve_contained_data_path(rel: Path) -> Path | None:
    """Resolve rel under data_root(); None when the path escapes the data root."""
    root = data_root().resolve()
    try:
        target = (root / rel).resolve()
        target.relative_to(root)
        return target
    except (OSError, ValueError):
        return None


def _admin_list_too_large(items: list[Any], *, cap: int, label: str) -> str | None:
    if len(items) > cap:
        return f"{label} exceeds maximum of {cap} items"
    return None


def _is_internal_admin_path(path: str) -> bool:
    return path.startswith("/api/internal/")


def _read_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


INTERNAL_JOBS: dict[str, dict[str, Any]] = _load_internal_jobs()


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


def _run_id_active_on_disk(run_id: str) -> bool:
    return any(entry.get("id") == run_id for entry in _read_active_runs())


def _fetcher_is_enrich(key: str) -> bool:
    return FETCHERS.get(key, {}).get("group") == "enrich"


def _filter_runs_by_lane(runs: list[Run], lane: str | None) -> list[Run]:
    """Restrict a run list to one lane. lane="fetcher" drops internal/enrich runs;
    lane="enrich" keeps enrich only; lane="internal" keeps admin jobs; None = all."""
    if lane == "fetcher":
        return [r for r in runs if not r._internal and not r._enrich]
    if lane == "enrich":
        return [r for r in runs if r._enrich]
    if lane == "internal":
        return [r for r in runs if r._internal]
    return list(runs)


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
        "_internal", "_internal_extra_args", "_enrich",
    )

    def __init__(
        self,
        key: str,
        refresh: bool = False,
        *,
        runs_dir: Path = RUNS_DIR,
        profile_id: str | None = None,
        internal: bool = False,
        enrich: bool = False,
        extra_args: list[str] | None = None,
    ) -> None:
        if internal:
            if key not in INTERNAL_JOBS:
                raise KeyError(key)
            spec = INTERNAL_JOBS[key]
        else:
            spec = FETCHERS[key]
        self.id: str = uuid.uuid4().hex[:12]
        self.key: str = key
        self.profile_id: str = profile_id or get_active_profile_id()
        self.label: str = spec["label"]
        self.refresh: bool = refresh
        self._internal = internal
        self._enrich = enrich and not internal
        self._internal_extra_args = list(extra_args or [])
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
        if self._enrich:
            summary["lane"] = "enrich"
        elif self._internal:
            summary["lane"] = "internal"
        else:
            summary["lane"] = "fetcher"
        if not self._internal:
            summary["group"] = FETCHERS.get(self.key, {}).get("group")
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
        if self._internal:
            return _internal_job_argv(
                INTERNAL_JOBS[self.key],
                self._internal_extra_args,
            )
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

    def __init__(
        self,
        runs_dir: Path | None = None,
        *,
        enable_watchdog: bool = True,
        reap_orphans: bool | None = None,
        restore_durable: bool = True,
    ) -> None:
        self._runs_dir = runs_dir or RUNS_DIR
        self._runs_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        # Three parallel lanes, each cap=1: fetcher (library/wishlist/prices),
        # enrich (HLTB/reviews/covers/tags), and internal (admin jobs).
        self._queue: queue.Queue[Run] = queue.Queue()
        self._enrich_queue: queue.Queue[Run] = queue.Queue()
        self._internal_queue: queue.Queue[Run] = queue.Queue()
        self._pending: list[Run] = []  # queued + active (all lanes), submission order
        self._history: deque[dict[str, Any]] = deque(
            _load_run_history_from(self._runs_dir / "history.json")[-MAX_HISTORY:],
            maxlen=MAX_HISTORY,
        )
        self._active: Run | None = None
        self._enrich_active: Run | None = None
        self._internal_active: Run | None = None
        self._runs_by_id: dict[str, Run] = {}
        self._last_queue_kick_at = 0.0
        self._watchdog_stop = threading.Event()
        # Only reap on explicit RunManager(runs_dir=...) for tests, or when the
        # dev server calls MANAGER._reap_orphan_processes() at boot. Importing
        # server.py (e.g. pytest) must not kill live fetchers from a running dev
        # server — that shared active.json lives on disk.
        if reap_orphans if reap_orphans is not None else runs_dir is not None:
            self._reap_orphan_processes()
        self._start_worker_thread()
        self._watchdog_thread: threading.Thread | None = None
        if enable_watchdog:
            self._watchdog_thread = threading.Thread(
                target=self._watchdog_loop, name="run-watchdog", daemon=True
            )
            self._watchdog_thread.start()
        # Production server defers restore to main() after bind; tests pass True.
        if restore_durable:
            self._restore_durable_queue()

    def _start_worker_thread(self) -> None:
        self._worker_thread = threading.Thread(
            target=self._worker_loop, args=("fetcher",), name="run-worker", daemon=True
        )
        self._worker_thread.start()
        self._enrich_worker_thread = threading.Thread(
            target=self._worker_loop, args=("enrich",), name="run-worker-enrich", daemon=True
        )
        self._enrich_worker_thread.start()
        self._internal_worker_thread = threading.Thread(
            target=self._worker_loop, args=("internal",), name="run-worker-internal", daemon=True
        )
        self._internal_worker_thread.start()

    def _ensure_worker_thread(self) -> None:
        """Restart any lane worker if its daemon thread died."""
        if not self._worker_thread.is_alive():
            print("[runs] fetcher worker thread died — restarting", file=sys.stderr, flush=True)
            self._worker_thread = threading.Thread(
                target=self._worker_loop, args=("fetcher",), name="run-worker", daemon=True
            )
            self._worker_thread.start()
        enrich = getattr(self, "_enrich_worker_thread", None)
        if enrich is None or not enrich.is_alive():
            print("[runs] enrich worker thread died — restarting", file=sys.stderr, flush=True)
            self._enrich_worker_thread = threading.Thread(
                target=self._worker_loop, args=("enrich",), name="run-worker-enrich", daemon=True
            )
            self._enrich_worker_thread.start()
        internal = getattr(self, "_internal_worker_thread", None)
        if internal is None or not internal.is_alive():
            print("[runs] internal worker thread died — restarting", file=sys.stderr, flush=True)
            self._internal_worker_thread = threading.Thread(
                target=self._worker_loop, args=("internal",), name="run-worker-internal", daemon=True
            )
            self._internal_worker_thread.start()

    def _resync_stalled_queue(self) -> int:
        """Put pending queued runs back on the worker queue when nothing is active.

        This heals the wedge where runs sit in ``_pending`` with status ``queued``
        but were never handed to ``_queue.get()`` (typically after the worker thread
        exited while the queue was empty). Runs both lanes independently.
        """
        return (
            self._resync_lane("fetcher")
            + self._resync_lane("enrich")
            + self._resync_lane("internal")
        )

    def _lane_queue(self, lane: str) -> queue.Queue[Run]:
        if lane == "internal":
            return self._internal_queue
        if lane == "enrich":
            return self._enrich_queue
        return self._queue

    def _lane_active(self, lane: str) -> Run | None:
        if lane == "internal":
            return self._internal_active
        if lane == "enrich":
            return self._enrich_active
        return self._active

    def _set_lane_active(self, lane: str, run: Run | None) -> None:
        if lane == "internal":
            self._internal_active = run
        elif lane == "enrich":
            self._enrich_active = run
        else:
            self._active = run

    def _run_in_lane(self, run: Run, lane: str) -> bool:
        if lane == "internal":
            return run._internal
        if lane == "enrich":
            return run._enrich
        return not run._internal and not run._enrich

    def _resync_lane(self, lane: str) -> int:
        lane_queue = self._lane_queue(lane)
        to_put: list[Run] = []
        with self._lock:
            active = self._lane_active(lane)
            if active is not None and active._finished.is_set():
                self._set_lane_active(lane, None)
                active = None
            if active is not None:
                return 0
            if lane_queue.qsize() > 0:
                return 0
            for r in self._pending:
                if not self._run_in_lane(r, lane):
                    continue
                if r.status == "queued" and not r._finished.is_set():
                    to_put.append(r)
        for r in to_put:
            lane_queue.put(r)
        if to_put:
            keys = ", ".join(r.key for r in to_put)
            print(
                f"[runs] re-queued {len(to_put)} stalled {lane} run(s): {keys}",
                file=sys.stderr,
                flush=True,
            )
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
            for active in (self._active, self._enrich_active, self._internal_active):
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
            for active in (self._active, self._enrich_active, self._internal_active):
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
        active_pid = get_active_profile_id()
        with self._lock:
            self._history = deque(
                _load_run_history_from(self._runs_dir / "history.json")[-MAX_HISTORY:],
                maxlen=MAX_HISTORY,
            )
            self._runs_by_id = {
                rid: run
                for rid, run in self._runs_by_id.items()
                if run.profile_id == active_pid
            }
            self._pending = [r for r in self._pending if r.profile_id == active_pid]
            if self._active is not None and self._active.profile_id != active_pid:
                self._active = None
            if (
                self._enrich_active is not None
                and self._enrich_active.profile_id != active_pid
            ):
                self._enrich_active = None
            if (
                self._internal_active is not None
                and self._internal_active.profile_id != active_pid
            ):
                self._internal_active = None

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

    def _register_pending_run(self, run: Run) -> None:
        """Cross-process hint so stream handlers can wait for another dev server."""
        entry = {
            "id": run.id,
            "pid": 0,
            "key": run.key,
            "label": run.label,
            "started_at": run.started_at or time.time(),
        }
        active = [e for e in _read_active_runs() if e.get("id") != run.id]
        active.append(entry)
        _write_active_runs(active)

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
            actives = [self._active, self._enrich_active, self._internal_active]
        kill_pids: list[int] = []
        for run in pending:
            changed, pids = run.cancel()
            if changed:
                kill_pids.extend(self._collect_pids_for_run(run, pids))
        for active in actives:
            if active is not None:
                changed, pids = active.cancel()
                if changed:
                    kill_pids.extend(self._collect_pids_for_run(active, pids))
        if kill_pids:
            for pid in dict.fromkeys(kill_pids):
                _terminate_pid(pid)
        _write_active_runs([])
        _save_durable_queue([])
        # Wake both worker lanes so their blocking queue.get() returns and the
        # threads exit, letting join_threads() finish immediately rather than
        # waiting out each 5s join timeout.
        for lane_queue in (self._queue, self._enrich_queue, self._internal_queue):
            try:
                lane_queue.put_nowait(None)
            except Exception:  # noqa: BLE001 - best-effort wakeup
                pass
        self.join_threads(timeout=5.0)

    def join_threads(self, timeout: float = 5.0) -> None:
        """Stop watchdog and wait for worker/watchdog threads (bounded)."""
        self._watchdog_stop.set()
        wt = getattr(self, "_watchdog_thread", None)
        if wt is not None and wt.is_alive():
            wt.join(timeout=timeout)
        if self._worker_thread.is_alive():
            self._worker_thread.join(timeout=timeout)
        enrich = getattr(self, "_enrich_worker_thread", None)
        if enrich is not None and enrich.is_alive():
            enrich.join(timeout=timeout)
        internal = getattr(self, "_internal_worker_thread", None)
        if internal is not None and internal.is_alive():
            internal.join(timeout=timeout)

    def submit(self, key: str, *, refresh: bool = False) -> Run:
        if key not in FETCHERS:
            raise KeyError(key)
        is_enrich = _fetcher_is_enrich(key)

        def _in_lane(r: Run) -> bool:
            if is_enrich:
                return r._enrich
            return not r._internal and not r._enrich

        with self._lock:
            active = self._enrich_active if is_enrich else self._active
            if active and active.key == key and active.status in _IN_FLIGHT_STATUSES:
                raise ValueError(f"{key} already queued or running")
            if any(
                _in_lane(r) and r.key == key and r.status in _IN_FLIGHT_STATUSES
                for r in self._pending
            ):
                raise ValueError(f"{key} already queued or running")
            in_flight = sum(
                1 for r in self._pending if _in_lane(r) and r.status in _IN_FLIGHT_STATUSES
            )
            if (
                active
                and active.status in _IN_FLIGHT_STATUSES
                and active not in self._pending
            ):
                in_flight += 1
            if in_flight >= 1:
                lane_label = "enrich" if is_enrich else "fetch"
                raise ValueError(
                    f"queue full — a {lane_label} is already running; "
                    "wait for it to finish before starting another"
                )
            profile_id = get_active_profile_id()
            run = Run(
                key,
                refresh=refresh,
                runs_dir=runs_dir(profile_id=profile_id),
                profile_id=profile_id,
                enrich=is_enrich,
            )
            self._pending.append(run)
            self._runs_by_id[run.id] = run
            (self._enrich_queue if is_enrich else self._queue).put(run)
        self._register_pending_run(run)
        self._persist_queue()
        self._ensure_worker_thread()
        return run

    def submit_internal(
        self,
        key: str,
        extra_args: list[str] | None = None,
        *,
        profile_id: str | None = None,
    ) -> Run:
        if key not in INTERNAL_JOBS:
            raise KeyError(key)
        with self._lock:
            active = self._internal_active
            if active and active.key == key and active.status in _IN_FLIGHT_STATUSES:
                raise ValueError(f"{key} already queued or running")
            if any(
                r._internal and r.key == key and r.status in _IN_FLIGHT_STATUSES
                for r in self._pending
            ):
                raise ValueError(f"{key} already queued or running")
            # The internal lane is independent of the fetcher lane: count only
            # internal in-flight runs so a running library fetch never blocks
            # admin Publish/Enrich (and vice versa). Internal jobs still
            # serialize with each other (cap 1) so claimSources/buildClaims
            # don't race the shared auto feed.
            in_flight = sum(
                1 for r in self._pending if r._internal and r.status in _IN_FLIGHT_STATUSES
            )
            if (
                active
                and active.status in _IN_FLIGHT_STATUSES
                and active not in self._pending
            ):
                in_flight += 1
            if in_flight >= 1:
                raise ValueError(
                    "an admin job is already running; "
                    "wait for it to finish before starting another"
                )
            pid = profile_id or get_active_profile_id()
            run = Run(
                key,
                runs_dir=runs_dir(profile_id=pid),
                profile_id=pid,
                internal=True,
                extra_args=extra_args or [],
            )
            self._pending.append(run)
            self._runs_by_id[run.id] = run
            self._internal_queue.put(run)
        self._register_pending_run(run)
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

    def cancel_all(
        self,
        *,
        profile_id: str | None = None,
        lane: str | None = None,
    ) -> list[dict[str, Any]]:
        """Cancel queued/running runs. lane="fetcher"/"internal" scopes to one lane.

        The dashboard passes lane="fetcher" so its Cancel button never kills an
        admin job (buildClaims/claimSources) running in the internal lane.
        """
        with self._lock:
            targets = [
                r for r in self._pending if r.status in _IN_FLIGHT_STATUSES
            ]
            for active in (self._active, self._enrich_active, self._internal_active):
                if (
                    active
                    and active.status in _IN_FLIGHT_STATUSES
                    and active not in targets
                ):
                    targets.append(active)
        targets = _filter_runs_by_lane(targets, lane)
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

    def force_reset(
        self,
        *,
        profile_id: str | None = None,
        lane: str | None = None,
    ) -> dict[str, Any]:
        """Kill tracked PIDs, clear queue state, finalize in-flight runs.

        lane="fetcher"/"internal" scopes the reset to a single lane so the
        dashboard force-reset leaves admin (internal) jobs untouched.
        """
        with self._lock:
            targets = [
                r for r in self._pending if r.status in _IN_FLIGHT_STATUSES
            ]
            for active in (self._active, self._enrich_active, self._internal_active):
                if (
                    active
                    and active.status in _IN_FLIGHT_STATUSES
                    and active not in targets
                ):
                    targets.append(active)
        targets = _filter_runs_by_lane(targets, lane)
        if profile_id is not None:
            targets = [r for r in targets if r.profile_id == profile_id]
        all_pids: list[int] = []
        if lane is None:
            for entry in _read_active_runs():
                pid = int(entry.get("pid") or 0)
                if pid <= 0:
                    continue
                if profile_id is not None and str(entry.get("profile_id") or "") != str(profile_id):
                    continue
                all_pids.append(pid)
        for run in targets:
            run.cancelled = True
            with run._lock:
                if run.status in _IN_FLIGHT_STATUSES and not run._finished.is_set():
                    run.status = "cancelled"
                    run.exit_code = -1
                    run.ended_at = time.time()
            all_pids.extend(self._collect_pids_for_run(run, []))
        target_ids = {run.id for run in targets}
        drains: list[queue.Queue] = []
        if lane in (None, "fetcher"):
            drains.append(self._queue)
        if lane in (None, "enrich"):
            drains.append(self._enrich_queue)
        if lane in (None, "internal"):
            drains.append(self._internal_queue)
        for drain in drains:
            while True:
                try:
                    drain.get_nowait()
                except queue.Empty:
                    break
        with self._lock:
            if lane is None:
                self._pending.clear()
                self._active = None
                self._enrich_active = None
                self._internal_active = None
            else:
                self._pending = [r for r in self._pending if r not in targets]
                if lane == "fetcher":
                    self._active = None
                elif lane == "enrich":
                    self._enrich_active = None
                elif lane == "internal":
                    self._internal_active = None
        if lane is None:
            _write_active_runs([])
        else:
            _write_active_runs(
                [e for e in _read_active_runs() if e.get("id") not in target_ids]
            )
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

    def _in_flight_targets(self, profile_id: str | None = None) -> list[Run]:
        """Queued or running jobs in either lane, including actives dropped from _pending."""
        with self._lock:
            targets = [
                r for r in self._pending if r.status in _IN_FLIGHT_STATUSES
            ]
            for active in (self._active, self._enrich_active, self._internal_active):
                if (
                    active
                    and active.status in _IN_FLIGHT_STATUSES
                    and active not in targets
                ):
                    targets.append(active)
        if profile_id is not None:
            targets = [r for r in targets if r.profile_id == profile_id]
        return targets

    def has_runs_for_profile(self, profile_id: str) -> bool:
        """True if any queued or running job in either lane is bound to this profile."""
        return bool(self._in_flight_targets(profile_id))

    def cancel_all_and_wait(
        self,
        timeout: float = SWITCH_CANCEL_WAIT_SEC,
    ) -> dict[str, Any]:
        """Cancel every in-flight job and wait for each to finish (bounded)."""
        targets = self._in_flight_targets()
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
            # active/queue cover the fetcher lane; enrich and internal are separate.
            active = (
                self._active.to_summary()
                if self._active and self._active.status in _IN_FLIGHT_STATUSES
                else None
            )
            queued = [
                r.to_summary()
                for r in self._pending
                if not r._internal
                and not r._enrich
                and r.status == "queued"
                and r is not self._active
            ]
            enrich_active = (
                self._enrich_active.to_summary()
                if self._enrich_active
                and self._enrich_active.status in _IN_FLIGHT_STATUSES
                else None
            )
            enrich_queue = [
                r.to_summary()
                for r in self._pending
                if r._enrich and r.status == "queued" and r is not self._enrich_active
            ]
            internal_active = (
                self._internal_active.to_summary()
                if self._internal_active
                and self._internal_active.status in _IN_FLIGHT_STATUSES
                else None
            )
            internal_queue = [
                r.to_summary()
                for r in self._pending
                if r._internal and r.status == "queued" and r is not self._internal_active
            ]
            history = list(self._history)
        return {
            "active": active,
            "queue": queued,
            "enrich_active": enrich_active,
            "enrich_queue": enrich_queue,
            "internal_active": internal_active,
            "internal_queue": internal_queue,
            "history": history,
        }

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
            if self._enrich_active is run:
                self._enrich_active = None
            if self._internal_active is run:
                self._internal_active = None
            if run in self._pending:
                self._pending.remove(run)
        self._unregister_active_process(run.id)
        self._append_history(run.to_summary(), profile_id=run.profile_id)
        self._persist_queue()
        self._prune_runs_by_id()

    def _worker_loop(self, lane: str = "fetcher") -> None:
        lane_queue = self._lane_queue(lane)
        while True:
            try:
                run = lane_queue.get()
                if run is None:
                    return
                if not run._finished.is_set():
                    with self._lock:
                        self._set_lane_active(lane, run)
                        if run.status == "queued":
                            run.status = "launching"
                    self._persist_queue()
                    try:
                        if run.status != "cancelled":
                            self._execute(run)
                    except Exception as exc:  # noqa: BLE001
                        if not run.cancelled:
                            run.status = "failed"
                            run.exit_code = -1
                            run.add_line("stderr", f"[server] worker error: {exc!r}")
                self._finalize_run(run)
            except Exception as exc:  # noqa: BLE001
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

        from baklog_fetcher_dispatch import apply_fetcher_env_mirror

        apply_fetcher_env_mirror(argv, env)

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
                    cwd=str(data_root()),
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
        max_run_sec = _max_run_seconds_for_key(run.key)
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
                if elapsed >= max_run_sec:
                    run.add_line(
                        "stderr",
                        f"[server] exceeded maximum runtime ({int(max_run_sec)}s) — "
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


MANAGER = RunManager(restore_durable=False)

# Pro-tier background scheduler (created/started in main(); None under pytest import).
SCHEDULER: Any = None
# Live dev server instance — used by POST /api/shutdown (tray graceful quit).
_DEV_HTTPD: ThreadingHTTPServer | None = None


def _header_hostname(value: str | None) -> str | None:
    if not value:
        return None
    host = (urlparse(value).hostname or "").lower()
    return host or None


def _normalize_host(raw: str | None) -> str:
    """Lowercased hostname with IPv6 brackets and any :port stripped.

    Handles ``127.0.0.1:8765``, ``localhost``, bracketed IPv6 ``[::1]:8765`` /
    ``[::1]``, and a bare ``::1`` — so loopback detection works for IPv6 too,
    not just ``split(':')[0]`` which mangles ``[::1]`` into ``[``.
    """
    if not raw:
        return ""
    host = raw.strip()
    if host.startswith("["):
        end = host.find("]")
        return (host[1:end] if end != -1 else host[1:]).lower()
    # A bare IPv6 literal (>1 colon, no bracket/port form we can split safely).
    if host.count(":") > 1:
        return host.lower()
    return host.split(":", 1)[0].lower()


def _request_host_is_local(handler: SimpleHTTPRequestHandler) -> bool:
    return _normalize_host(handler.headers.get("Host", "")) in _LOCAL_HOSTNAMES


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


def _csrf_allowed_strict(handler: SimpleHTTPRequestHandler) -> bool:
    """Stricter CSRF for profile mutations — require explicit app header or bearer."""
    from shared.supabase_auth import auth_enabled, verify_bearer_user

    if auth_enabled() and verify_bearer_user(handler.headers.get("Authorization")):
        return True
    if not _request_host_is_local(handler):
        return False
    return handler.headers.get(_BAKLOG_LOCAL_HEADER) == "1"


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


def _static_class(path_only: str) -> str:
    return _static_class_impl(path_only, admin_enabled=ADMIN_ENABLED)


def _path_only(handler: SimpleHTTPRequestHandler) -> str:
    return handler.path.split("?", 1)[0]


def _send_auth_required(handler: SimpleHTTPRequestHandler) -> None:
    if handler.command.upper() == "HEAD":
        handler.send_response(HTTPStatus.UNAUTHORIZED)
        handler.end_headers()
    else:
        _send_json(handler, HTTPStatus.UNAUTHORIZED, {"error": "sign in required"})


def _bind_request_user(handler: SimpleHTTPRequestHandler) -> str | None:
    """Verify bearer, ensure profile dir, pin request context. None after 401."""
    from shared.account_profiles import ensure_profile_for_user
    from shared.supabase_auth import local_profiles_enabled, verify_bearer_user

    user = verify_bearer_user(handler.headers.get("Authorization"))
    if not user:
        _send_auth_required(handler)
        return None
    if local_profiles_enabled():
        # JWT proves identity; active profile comes from profiles/index.json.
        return user["id"]
    pid = ensure_profile_for_user(user["id"], user.get("email") or None)
    set_request_profile_id(pid)
    return pid


def _bind_bearer_profile(handler: SimpleHTTPRequestHandler) -> bool:
    """Verify bearer and pin request profile. Return False after sending 401."""
    return _bind_request_user(handler) is not None


def _gate_static(handler: SimpleHTTPRequestHandler) -> bool:
    """Gate static catalog/cache paths when Supabase auth is on. Return False if handled."""
    from shared.supabase_auth import auth_enabled, local_profiles_enabled, verify_bearer_user

    path_only = _path_only(handler)
    kind = _static_class(path_only)
    if kind == "deny":
        handler.send_error(HTTPStatus.NOT_FOUND, "Not found")
        return False
    if kind == "data" and auth_enabled():
        if local_profiles_enabled():
            if not verify_bearer_user(handler.headers.get("Authorization")):
                _send_auth_required(handler)
                return False
            return True
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


def _maybe_serve_empty_claims_json(handler: SimpleHTTPRequestHandler, path: str) -> bool:
    if path.lower() != "/free_claims.json":
        return False
    if free_claims_path().is_file():
        return False
    _send_json(handler, HTTPStatus.OK, {"generated_at": None, "items": []})
    return True


def _maybe_serve_empty_sponsors_json(handler: SimpleHTTPRequestHandler, path: str) -> bool:
    if path.lower() != "/sponsors.json":
        return False
    if sponsors_path().is_file():
        return False
    _send_json(handler, HTTPStatus.OK, {"version": 1, "generated_at": None, "items": []})
    return True


# Minimal stubs when a profile has not run enrichment fetchers yet. Return 200
# instead of 404 so the browser console stays clean; never fall back to another
# profile's repo-root cache (see find_profile_cache_http / find_dashboard_cache_meta_404_console).
_EMPTY_CACHE_META_JSON: dict[str, dict[str, Any]] = {
    "hltb_map.json": {"fetched_at": None},
    "steam_review_map.json": {"fetched_at": None},
    "cross_store_images_meta.json": {"fetched_at": None, "no_steam_match": []},
    "steam_tags_meta.json": {"fetched_at": None},
    "protondb_map.json": {"fetched_at": None},
    "fx_rates.json": {"fetched_at": None, "rates": {}},
}


def _maybe_serve_empty_cache_meta_json(handler: SimpleHTTPRequestHandler, path: str) -> bool:
    parts = [p for p in path.split("/") if p]
    if len(parts) != 2 or parts[0] != "cache":
        return False
    name = parts[1]
    if name not in PROFILE_CACHE_JSON_FILES:
        return False
    if cache_json_path(name).is_file():
        return False
    payload = _EMPTY_CACHE_META_JSON.get(name)
    if payload is None:
        return False
    _send_json(handler, HTTPStatus.OK, payload)
    return True


def _read_json_body(
    handler: SimpleHTTPRequestHandler,
    *,
    max_bytes: int = PERSONAL_MAX_BYTES,
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        length = int(handler.headers.get("Content-Length") or 0)
    except ValueError:
        return None, "invalid Content-Length"
    if length <= 0:
        return None, "empty body"
    if length > max_bytes:
        return None, f"body too large ({length} > {max_bytes})"
    try:
        raw = handler.rfile.read(length).decode("utf-8")
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"invalid JSON: {exc!r}"
    if not isinstance(payload, dict):
        return None, "payload must be a JSON object"
    return payload, None


# Small JSON bodies for credential/control endpoints (master password, secrets
# export/import metadata). The encrypted secrets bundle itself rides in the
# import body, so that one endpoint uses a larger, bundle-sized cap below.
_AUTH_JSON_MAX_BYTES = 64 * 1024
# Bundle base64 (~4/3 inflation over the 100 MB ciphertext cap) plus JSON
# framing. Replaces the previous unbounded read on the import endpoint.
_SECRETS_IMPORT_MAX_BYTES = 160 * 1024 * 1024


def _api_error(
    handler: SimpleHTTPRequestHandler,
    status: int,
    code: str,
    exc: BaseException | None = None,
) -> None:
    """Log the underlying exception server-side (redacted) and return a generic
    ``{"error": code}`` to the client. Keeps stack details / secret-bearing
    messages out of HTTP responses while preserving local debuggability."""
    if exc is not None:
        try:
            detail = _redact_log_line(f"{type(exc).__name__}: {exc}")
        except Exception:  # noqa: BLE001 - never let logging crash the handler
            detail = type(exc).__name__
        print(f"[api] {code}: {detail}", file=sys.stderr, flush=True)
    _send_json(handler, status, {"error": code})


def _api_path(handler: SimpleHTTPRequestHandler) -> str:
    raw = handler.path.split("?", 1)[0]
    return raw.rstrip("/") or "/"


def _require_api_auth(handler: SimpleHTTPRequestHandler) -> bool:
    """Authenticate /api/* when Supabase auth is enabled. Return False if rejected."""
    from shared.supabase_auth import auth_enabled

    path = _api_path(handler)
    if not path.startswith("/api/"):
        return True
    if path in ("/api/config", "/api/update-check", "/api/diagnostics"):
        return True
    if ADMIN_ENABLED and _is_admin_exempt_api(path):
        return True
    if not auth_enabled():
        return True
    return _bind_request_user(handler) is not None


def _is_admin_exempt_api(path: str) -> bool:
    """Endpoints the local admin console (BAKLOG_ADMIN=1) may reach without a
    Supabase bearer token. Covers internal admin routes plus the RunManager
    status/stream/control endpoints the Jobs run-console polls (the admin console
    is local-only and does not carry an account JWT)."""
    if path.startswith("/api/internal/"):
        return True
    if path == "/api/runs" or path.startswith("/api/runs/"):
        return True
    if path.startswith("/api/run/"):
        return True
    if path.startswith("/api/stream/"):
        return True
    return False


def _profile_admin_blocked() -> bool:
    from shared.supabase_auth import auth_enabled, local_profiles_enabled

    return auth_enabled() and not local_profiles_enabled()


def _profile_run_isolation_enabled() -> bool:
    """Scope run access/history to the active profile when isolation matters."""
    from shared.supabase_auth import auth_enabled

    if auth_enabled():
        return True
    from shared.profile_paths import list_profiles

    return len(list_profiles()) > 1


def _run_accessible(run: Run | None) -> Run | None:
    """Only the active profile may access a run when isolation is enabled."""
    if run is None:
        return None
    if not _profile_run_isolation_enabled():
        return run
    if run.profile_id == get_active_profile_id():
        return run
    return None


def _stream_terminal_accessible(run_id: str) -> dict[str, Any] | None:
    terminal = MANAGER.stream_terminal_summary(run_id)
    if terminal is None:
        return None
    if (
        _profile_run_isolation_enabled()
        and terminal.get("profile_id") != get_active_profile_id()
    ):
        return None
    return terminal


def _resolve_stream_target(run_id: str) -> tuple[Run | None, dict[str, Any] | None]:
    run = _run_accessible(MANAGER.get(run_id))
    if run is not None:
        return run, None
    return None, _stream_terminal_accessible(run_id)


def _wait_for_stream_target(
    run_id: str, *, since: int
) -> tuple[Run | None, dict[str, Any] | None]:
    run, terminal = _resolve_stream_target(run_id)
    if run is not None or terminal is not None or since > 0:
        return run, terminal
    short_deadline = time.time() + _STREAM_ATTACH_SHORT_WAIT_SEC
    while time.time() < short_deadline:
        run, terminal = _resolve_stream_target(run_id)
        if run is not None or terminal is not None:
            return run, terminal
        time.sleep(_STREAM_ATTACH_POLL_SEC)
    if not _run_id_active_on_disk(run_id):
        return None, None
    long_deadline = time.time() + _STREAM_ATTACH_LONG_WAIT_SEC
    while time.time() < long_deadline:
        run, terminal = _resolve_stream_target(run_id)
        if run is not None or terminal is not None:
            return run, terminal
        time.sleep(_STREAM_ATTACH_POLL_SEC)
    return None, None


class Handler(SimpleHTTPRequestHandler):
    def handle_one_request(self) -> None:  # http.server API
        _note_activity()  # reset the idle-shutdown countdown on any client contact
        super().handle_one_request()

    def handle(self) -> None:
        try:
            super().handle()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            # Client cancelled an in-flight request (e.g. rapid page reload).
            # Benign on Windows (WinError 10053); skip the noisy traceback.
            pass
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

    def _reject_if_csrf_strict(self) -> bool:
        """Stricter CSRF gate for profile admin routes."""
        if _csrf_allowed_strict(self):
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
        path = self.path.split("?", 1)[0]
        path_lower = path.lower()
        if (
            is_frozen()
            and serve_built_frontend()
            and _is_immutable_built_asset(path)
        ):
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        elif path_lower.endswith(self._NO_CACHE_SUFFIXES) or path_lower in ("/", ""):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def translate_path(self, path: str) -> str:
        """Serve catalog and cache JSON from the active profile root (legacy or profiles/<id>/)."""
        norm = _normalize_static_path(path.split("?", 1)[0])
        clean = norm.lstrip("/")
        if _static_class(norm) == "deny":
            return str(profile_root() / ".profile_static_blocked" / clean)
        if clean.startswith("profiles/"):
            # Block direct static access to another profile's tree (use top-level paths).
            return str(profile_root() / ".profile_static_blocked" / clean)
        if _LIBRARY_JSON_RE.match(norm) or norm.lower() in (
            "/itad_prices.json",
            "/free_claims.json",
            "/sponsors.json",
        ):
            leaf = clean.split("/")[-1]
            if leaf == "itad_prices.json":
                disk = catalog_path("itad_prices.json")
            elif leaf == "free_claims.json":
                disk = free_claims_path()
            elif leaf == "sponsors.json":
                disk = sponsors_path()
            else:
                disk = catalog_path(leaf)
            if disk.is_file():
                resolved = str(disk)
                if _resolved_static_path_allowed(resolved):
                    return resolved
                return str(profile_root() / ".profile_static_blocked" / clean)
        if clean.startswith("cache/"):
            name = clean.split("/", 1)[1]
            if name in PROFILE_CACHE_JSON_FILES:
                # Always resolve to the active profile's cache path. For a legacy
                # (default) layout this is repo-root cache; for profiles/<id>/ it
                # is the profile cache. A missing file 404s instead of leaking the
                # default profile's enrichment data into another profile's chips.
                resolved = str(cache_json_path(name))
                if _resolved_static_path_allowed(resolved):
                    return resolved
                return str(profile_root() / ".profile_static_blocked" / clean)
        resolved = super().translate_path(path)
        # Python 3.13+ translate_path returns a trailing-slash directory for "/"
        # instead of resolving index.html; map that here so the app shell loads.
        resolved_path = Path(resolved)
        if resolved_path.is_dir():
            for leaf in ("index.html", "index.htm"):
                index = resolved_path / leaf
                if index.is_file():
                    resolved = str(index)
                    break
        if not _resolved_static_path_allowed(resolved):
            return str(profile_root() / ".profile_static_blocked" / clean)
        return resolved

    def _begin_request(self) -> None:
        clear_request_profile_id()

    # ---- routing -----------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802 - http.server API
        self._begin_request()
        path = _api_path(self)
        if path == "/api/config":
            self._handle_config_get()
            return
        if path in ("/api/update-check", "/api/diagnostics"):
            self._handle_support_get(path)
            return
        if path.startswith("/oauth/epic/callback"):
            self._handle_epic_oauth_callback()
            return
        if path.startswith("/api/stream/"):
            self._handle_stream(path[len("/api/stream/"):])
            return
        if path.startswith("/api/auth/") and path.endswith("/stream"):
            if not _authorize_stream(self):
                return
            rest = path[len("/api/auth/") : -len("/stream")].strip("/")
            self._handle_auth_stream(rest)
            return
        if path == "/api/internal/jobs":
            if not ADMIN_ENABLED:
                self.send_error(HTTPStatus.NOT_FOUND, "Not found")
                return
            server_internal_routes.handle_internal_jobs_get(self)
            return
        if path == "/api/internal/free-claims":
            if not ADMIN_ENABLED:
                self.send_error(HTTPStatus.NOT_FOUND, "Not found")
                return
            server_internal_routes.handle_internal_free_claims_get(self)
            return
        if path == "/api/internal/sponsors":
            if not ADMIN_ENABLED:
                self.send_error(HTTPStatus.NOT_FOUND, "Not found")
                return
            server_internal_routes.handle_internal_sponsors_get(self)
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
        if _maybe_serve_empty_claims_json(self, path_only):
            return
        if _maybe_serve_empty_sponsors_json(self, path_only):
            return
        if _maybe_serve_empty_cache_meta_json(self, path_only):
            return
        if _maybe_serve_built_index(self, path_only):
            return
        super().do_GET()

    def do_HEAD(self) -> None:  # noqa: N802 - http.server API
        self._begin_request()
        if _api_path(self) == "/api/config":
            self._handle_config_get()
            return
        if not _require_api_auth(self):
            return
        if not _gate_static(self):
            return
        super().do_HEAD()

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        self._begin_request()
        path = _api_path(self)
        if path == "/api/shutdown":
            if self._reject_if_csrf_strict():
                return
            self._handle_shutdown()
            return
        if _is_internal_admin_path(path):
            if self._reject_if_csrf_strict():
                return
        elif self._reject_if_csrf():
            return
        if path.startswith("/api/internal/run/"):
            if not ADMIN_ENABLED:
                self.send_error(HTTPStatus.NOT_FOUND, "Not found")
                return
            key = path[len("/api/internal/run/") :].strip("/").split("/", 1)[0]
            server_internal_routes.handle_internal_submit(self, key)
            return
        if path == "/api/internal/free-claims/enrich":
            if not ADMIN_ENABLED:
                self.send_error(HTTPStatus.NOT_FOUND, "Not found")
                return
            server_internal_routes.handle_internal_free_claims_enrich(self)
            return
        if path == "/api/internal/free-claims/preview":
            if not ADMIN_ENABLED:
                self.send_error(HTTPStatus.NOT_FOUND, "Not found")
                return
            server_internal_routes.handle_internal_free_claims_preview(self)
            return
        if path == "/api/auth/stream-ticket":
            from shared.supabase_auth import auth_enabled, verify_bearer_user

            # Admin console has no Supabase JWT; mint tickets with localhost CSRF only.
            if (
                auth_enabled()
                and ADMIN_ENABLED
                and verify_bearer_user(self.headers.get("Authorization")) is None
                and _request_host_is_local(self)
                and self.headers.get(_BAKLOG_LOCAL_HEADER) == "1"
            ):
                self._handle_stream_ticket_mint()
                return
        if path == "/api/license/activate":
            self._handle_license_activate()
            return
        if not _require_api_auth(self):
            return
        if path == "/api/auth/stream-ticket":
            self._handle_stream_ticket_mint()
            return
        if path.rstrip("/") == "/api/runs/cancel":
            self._handle_cancel_all()
            return
        if path.startswith("/api/run/"):
            rest = path[len("/api/run/"):].strip("/")
            if rest.endswith("/cancel"):
                run_id = rest[: -len("/cancel")].strip("/")
                self._handle_cancel(run_id)
            else:
                self._handle_submit(rest)
            return
        if path.startswith("/api/auth/") and path.endswith("/start"):
            provider = path[len("/api/auth/") : -len("/start")].strip("/")
            self._handle_auth_start(provider)
            return
        if path.startswith("/api/auth/") and path.endswith("/oauth-url"):
            provider = path[len("/api/auth/") : -len("/oauth-url")].strip("/")
            if provider == "epic":
                self._handle_epic_oauth_url()
            else:
                _send_json(self, HTTPStatus.NOT_FOUND, {"error": f"no oauth-url for {provider}"})
            return
        if path.startswith("/api/auth/") and path.endswith("/open-url"):
            provider = path[len("/api/auth/") : -len("/open-url")].strip("/")
            self._handle_auth_open_url(provider)
            return
        if path.startswith("/api/auth/") and path.endswith("/disconnect"):
            provider = path[len("/api/auth/") : -len("/disconnect")].strip("/")
            self._handle_auth_disconnect(provider)
            return
        if path.startswith("/api/auth/") and path.endswith("/enable"):
            provider = path[len("/api/auth/") : -len("/enable")].strip("/")
            self._handle_auth_enable(provider)
            return
        if path == "/api/auth/master-password":
            self._handle_auth_master_password()
            return
        if path == "/api/auth/secrets/export" or path.startswith("/api/auth/secrets/import"):
            if self._reject_if_csrf_strict():
                return
        if path == "/api/auth/secrets/export":
            self._handle_auth_secrets_export()
            return
        if path.startswith("/api/auth/secrets/import"):
            self._handle_auth_secrets_import()
            return
        if path == "/api/profiles":
            if self._reject_if_csrf_strict():
                return
            self._handle_profiles_create()
            return
        if path == "/api/profiles/active":
            if self._reject_if_csrf_strict():
                return
            self._handle_profiles_set_active()
            return
        if path.startswith("/api/profiles/") and path.endswith("/pin"):
            if self._reject_if_csrf_strict():
                return
            profile_id = path[len("/api/profiles/") : -len("/pin")].strip("/")
            if profile_id:
                self._handle_profiles_set_pin(profile_id)
                return
        if path == "/api/personal":
            if self._reject_if_csrf_strict():
                return
            self._handle_personal_put()
            return
        if path == "/api/catalogs/import":
            if self._reject_if_csrf_strict():
                return
            from shared.server_catalog_import import handle_catalogs_import_post

            handle_catalogs_import_post(self)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")

    def do_DELETE(self) -> None:  # noqa: N802 - http.server API
        self._begin_request()
        if self._reject_if_csrf():
            return
        if not _require_api_auth(self):
            return
        path = _api_path(self)
        if path.startswith("/api/profiles/") and path.endswith("/pin"):
            if self._reject_if_csrf_strict():
                return
            profile_id = path[len("/api/profiles/") : -len("/pin")].strip("/")
            if profile_id:
                self._handle_profiles_clear_pin(profile_id)
                return
        if path.startswith("/api/profiles/"):
            if self._reject_if_csrf_strict():
                return
            profile_id = path[len("/api/profiles/") :].strip("/")
            if profile_id and profile_id not in ("active",):
                self._handle_profiles_delete(profile_id)
                return
        self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")

    def do_PUT(self) -> None:  # noqa: N802 - http.server API
        self._begin_request()
        path = _api_path(self)
        if _is_internal_admin_path(path):
            if self._reject_if_csrf_strict():
                return
        elif self._reject_if_csrf():
            return
        if path == "/api/internal/free-claims/approved":
            if not ADMIN_ENABLED:
                self.send_error(HTTPStatus.NOT_FOUND, "Not found")
                return
            server_internal_routes.handle_internal_free_claims_approved_put(self)
            return
        if path == "/api/internal/free-claims":
            if not ADMIN_ENABLED:
                self.send_error(HTTPStatus.NOT_FOUND, "Not found")
                return
            server_internal_routes.handle_internal_free_claims_put(self)
            return
        if path == "/api/internal/sponsors":
            if not ADMIN_ENABLED:
                self.send_error(HTTPStatus.NOT_FOUND, "Not found")
                return
            server_internal_routes.handle_internal_sponsors_put(self)
            return
        if not _require_api_auth(self):
            return
        if path == "/api/personal":
            if self._reject_if_csrf_strict():
                return
            self._handle_personal_put()
            return
        if path.startswith("/api/profiles/"):
            if self._reject_if_csrf_strict():
                return
            profile_id = path[len("/api/profiles/") :].strip("/")
            if profile_id and profile_id not in ("active", "pin") and not profile_id.endswith("/pin"):
                self._handle_profiles_rename(profile_id)
                return
        if path.startswith("/api/auth/") and path.endswith("/credentials"):
            provider = path[len("/api/auth/") : -len("/credentials")].strip("/")
            self._handle_auth_credentials(provider)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")

    # ---- handlers ----------------------------------------------------------
    def _handle_config_get(self) -> None:
        from shared.entitlement import current_plan, maybe_refresh_local_license
        from shared.polar_license import polar_configured
        from shared.pro_checkout import pro_checkout_enabled, public_checkout_urls
        from shared.supabase_auth import auth_enabled, public_auth_config

        maybe_refresh_local_license()
        config = dict(public_auth_config())
        # Entitlement: signed JWT claim (when a bearer is sent) wins, else the
        # local license file / BAKLOG_PLAN override. Defaults to "free".
        config["plan"] = current_plan(self.headers.get("Authorization"))
        config["licenseActivation"] = polar_configured() and not auth_enabled()
        config["proCheckoutEnabled"] = pro_checkout_enabled()
        config["proCheckout"] = public_checkout_urls()
        config["frozen"] = is_frozen()
        config["version"] = _app_version()
        config["chromium_available"] = _chromium_available()
        from shared.install_paths import frozen_bundle_dir, is_portable_frozen
        from shared.server_support import is_running_from_temp_dir, redact_user_path

        config["running_from_temp"] = is_frozen() and is_running_from_temp_dir(frozen_bundle_dir())
        if is_frozen():
            config["data_dir_path"] = redact_user_path(ROOT)
            config["portable"] = is_portable_frozen()
        _send_json(self, HTTPStatus.OK, config)

    def _handle_support_get(self, path: str) -> None:
        from shared.server_support import build_diagnostics_payload, build_update_check_payload

        if path == "/api/update-check":
            _send_json(self, HTTPStatus.OK, build_update_check_payload(_app_version()))
            return
        _send_json(
            self,
            HTTPStatus.OK,
            _redact_diagnostics_payload(
                build_diagnostics_payload(
                    data_root=ROOT,
                    version=_app_version(),
                    load_run_history=_load_run_history,
                )
            ),
        )

    def _handle_fetchers(self) -> None:
        try:
            data = {
                "server_platform": sys.platform,
                "fetchers": [
                    {
                        "key": k,
                        "label": v["label"],
                        "cmd": _fetcher_cmd_label(v["argv"]),
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
            _api_error(self, HTTPStatus.INTERNAL_SERVER_ERROR, "profiles_get_failed", exc)

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
            _send_json(self, HTTPStatus.CREATED, created)
        except ValueError as exc:
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except OSError as exc:
            _send_json(
                self,
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": f"profile create failed: {exc}"},
            )

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
            from shared.profiles import (
                clear_pin_failures,
                pin_rate_limit_error,
                profile_requires_pin,
                record_pin_failure,
                set_active_profile,
                verify_profile_pin,
            )

            locked = pin_rate_limit_error(profile_id)
            if locked:
                _send_json(self, HTTPStatus.TOO_MANY_REQUESTS, {"error": locked})
                return
            if profile_requires_pin(profile_id):
                pin = str(payload.get("pin") or "").strip()
                if not pin:
                    _send_json(
                        self,
                        HTTPStatus.UNAUTHORIZED,
                        {"error": "pin_required"},
                    )
                    return
                if not verify_profile_pin(profile_id, pin):
                    record_pin_failure(profile_id)
                    _send_json(
                        self,
                        HTTPStatus.UNAUTHORIZED,
                        {"error": "incorrect_pin"},
                    )
                    return
            clear_pin_failures(profile_id)
            from auth.manager import has_active_sessions

            if has_active_sessions():
                _send_json(
                    self,
                    HTTPStatus.CONFLICT,
                    {"error": "Finish or cancel the sign-in window before switching profiles."},
                )
                return
            MANAGER.cancel_all_and_wait()
            result = set_active_profile(profile_id)
            _refresh_personal_paths()
            _send_json(self, HTTPStatus.OK, result)
        except ValueError as exc:
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def _handle_profiles_set_pin(self, profile_id: str) -> None:
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
            from shared.profiles import set_profile_pin

            pin = str(payload.get("pin") or "")
            current = str(payload.get("currentPin") or payload.get("current_pin") or "").strip() or None
            set_profile_pin(profile_id, pin, current_pin=current)
            _send_json(self, HTTPStatus.OK, {"ok": True, "hasPin": True})
        except ValueError as exc:
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def _handle_profiles_clear_pin(self, profile_id: str) -> None:
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
            from shared.profiles import clear_profile_pin

            current = str(payload.get("currentPin") or payload.get("current_pin") or payload.get("pin") or "")
            clear_profile_pin(profile_id, current)
            _send_json(self, HTTPStatus.OK, {"ok": True, "hasPin": False})
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
            _send_json(self, HTTPStatus.FORBIDDEN, {
                "error": "profile management is disabled while account sign-in is enabled"})
            return
        if MANAGER.has_runs_for_profile(profile_id):
            _send_json(self, HTTPStatus.CONFLICT, {"error": (
                "This profile has a fetch running or queued. "
                "Cancel its runs or let them finish before deleting."
            )})
            return
        current_pin: str | None = None
        if int(self.headers.get("Content-Length") or 0) > 0:
            payload, err = _read_json_body(self)
            if err:
                _send_json(self, HTTPStatus.BAD_REQUEST, {"error": err})
                return
            current_pin = str((payload or {}).get("currentPin") or (payload or {}).get("pin") or "").strip() or None
        try:
            from shared.profiles import delete_profile

            delete_profile(profile_id, current_pin=current_pin)
            _refresh_personal_paths()
            _send_json(self, HTTPStatus.OK, {"ok": True})
        except ValueError as exc:
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except OSError as exc:
            _send_json(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"profile delete failed: {exc}"})

    def _handle_personal_get(self) -> None:
        try:
            doc = _load_personal_doc()
        except PersonalCorruptError as exc:
            _send_json(self, HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(exc)})
            return
        except Exception as exc:  # noqa: BLE001 - the file is small, anything is unexpected here
            _api_error(self, HTTPStatus.INTERNAL_SERVER_ERROR, "personal_load_failed", exc)
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
        allow_empty = self.headers.get(_BAKLOG_ALLOW_EMPTY_HEADER) == "1"
        try:
            doc = _save_personal_doc(payload, allow_empty=allow_empty)
        except PersonalEmptyOverwriteError as exc:
            _send_json(self, HTTPStatus.CONFLICT, {"error": str(exc)})
            return
        except PersonalCorruptError as exc:
            _send_json(self, HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(exc)})
            return
        except ValueError as exc:
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        except OSError as exc:
            _api_error(self, HTTPStatus.INTERNAL_SERVER_ERROR, "personal_write_failed", exc)
            return
        _send_json(self, HTTPStatus.OK, doc)

    def _handle_runs(self) -> None:
        snap = MANAGER.snapshot()
        if _profile_run_isolation_enabled():
            pid = get_active_profile_id()
            active = snap.get("active")
            if active and active.get("profile_id") != pid:
                snap["active"] = None
            snap["queue"] = [
                r for r in (snap.get("queue") or []) if r.get("profile_id") == pid
            ]
            internal_active = snap.get("internal_active")
            if internal_active and internal_active.get("profile_id") != pid:
                snap["internal_active"] = None
            snap["internal_queue"] = [
                r for r in (snap.get("internal_queue") or []) if r.get("profile_id") == pid
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
        lane = (qs.get("lane", [""])[0] or "").strip().lower() or None
        if lane not in (None, "fetcher", "internal"):
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": f"invalid lane: {lane}"})
            return
        scope_pid = None
        if auth_enabled():
            scope_pid = _bind_request_user(self)
            if scope_pid is None:
                return
        if force:
            payload = MANAGER.force_reset(profile_id=scope_pid, lane=lane)
        else:
            payload = {"cancelled": MANAGER.cancel_all(profile_id=scope_pid, lane=lane)}
        _send_json(self, HTTPStatus.OK, payload)

    def _handle_shutdown(self) -> None:
        """Graceful shutdown for the tray launcher (localhost + X-BAKLOG-Local only)."""
        _send_json(self, HTTPStatus.OK, {"ok": True})
        threading.Thread(
            target=_trigger_dev_shutdown, name="dev-shutdown", daemon=True
        ).start()

    def _handle_license_activate(self) -> None:
        """Validate a Polar license key and persist license.json (pure-local mode)."""
        from shared.entitlement import activate_local_license_key, current_plan

        payload, err = _read_json_body(self)
        if err:
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": err})
            return
        raw_key = payload.get("key") if isinstance(payload, dict) else ""
        ok, message = activate_local_license_key(str(raw_key or ""))
        status = HTTPStatus.OK if ok else HTTPStatus.BAD_REQUEST
        _send_json(
            self,
            status,
            {"ok": ok, "message": message, "plan": current_plan(None)},
        )

    def _handle_auth_session_get(self) -> None:
        from shared.server_auth_session import handle_auth_session_get

        handle_auth_session_get(self)

    def _handle_stream_ticket_mint(self) -> None:
        """Limited-reuse ticket for EventSource streams (cannot send Authorization)."""
        payload, err = _read_json_body(self)
        if err == "empty body":
            payload = {}
        elif err:
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": err})
            return
        assert payload is not None
        run_id: str | None = None
        profile_id = get_active_profile_id()
        run = None
        raw_run = payload.get("run_id") if isinstance(payload, dict) else None
        if raw_run:
            run_id = str(raw_run).strip().split("/", 1)[0].split("?", 1)[0] or None
            run = MANAGER.get(run_id) if run_id else None
            if run is not None:
                profile_id = run.profile_id
        ticket = _mint_stream_ticket(profile_id, run_id=run_id)
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
            _api_error(self, HTTPStatus.INTERNAL_SERVER_ERROR, "auth_status_failed", exc)

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
            _api_error(self, HTTPStatus.INTERNAL_SERVER_ERROR, "auth_open_url_failed", exc)

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
            _api_error(self, HTTPStatus.INTERNAL_SERVER_ERROR, "auth_start_failed", exc)

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
            from clients.epic_client import build_epic_oauth_login_url

            state = secrets.token_urlsafe(24)
            _register_epic_oauth_state(state, profile_id=get_active_profile_id())
            redirect_uri = self._public_callback_url("/oauth/epic/callback")
            url = build_epic_oauth_login_url(redirect_uri, state)
            _send_json(self, HTTPStatus.OK, {"url": url, "state": state})
        except Exception as exc:  # noqa: BLE001
            _api_error(self, HTTPStatus.INTERNAL_SERVER_ERROR, "epic_oauth_url_failed", exc)

    def _handle_auth_disconnect(self, provider: str) -> None:
        try:
            from auth.manager import disconnect

            disconnect(provider)
            _send_json(self, HTTPStatus.OK, {"ok": True})
        except KeyError:
            _send_json(self, HTTPStatus.NOT_FOUND, {"error": f"unknown provider: {provider}"})
        except Exception as exc:  # noqa: BLE001
            _api_error(self, HTTPStatus.INTERNAL_SERVER_ERROR, "auth_disconnect_failed", exc)

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
            _api_error(self, HTTPStatus.INTERNAL_SERVER_ERROR, "auth_enable_failed", exc)

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
            _api_error(self, HTTPStatus.INTERNAL_SERVER_ERROR, "credentials_failed", exc)

    def _handle_auth_master_password(self) -> None:
        payload, err = _read_json_body(self, max_bytes=_AUTH_JSON_MAX_BYTES)
        if err == "empty body":
            payload = {}
        elif err:
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": err})
            return
        assert payload is not None
        try:
            from auth.manager import set_master_password

            set_master_password(payload.get("password"))
            _send_json(self, HTTPStatus.OK, {"ok": True})
        except ValueError as exc:
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            _api_error(self, HTTPStatus.INTERNAL_SERVER_ERROR, "master_password_failed", exc)

    def _handle_auth_secrets_export(self) -> None:
        payload, err = _read_json_body(self, max_bytes=_AUTH_JSON_MAX_BYTES)
        if err == "empty body":
            payload = {}
        elif err:
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": err})
            return
        assert payload is not None
        try:
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
            _api_error(self, HTTPStatus.INTERNAL_SERVER_ERROR, "export_failed", exc)

    def _handle_auth_secrets_import(self) -> None:
        import base64

        # JSON-only: {"passphrase": str, "blob": base64}. The legacy
        # octet-stream + ?passphrase= query-string fallback is removed — a
        # passphrase in the URL leaks into request logs / browser history.
        payload, err = _read_json_body(self, max_bytes=_SECRETS_IMPORT_MAX_BYTES)
        if err:
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": err})
            return
        assert payload is not None
        try:
            passphrase = str(payload.get("passphrase") or "")
            blob_b64 = payload.get("blob")
            if isinstance(blob_b64, str):
                try:
                    # binascii.Error subclasses ValueError, so this catch covers
                    # malformed base64 too.
                    blob = base64.b64decode(blob_b64, validate=True)
                except ValueError as exc:
                    raise ValueError("blob is not valid base64") from exc
            else:
                blob = b""
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
            _api_error(self, HTTPStatus.INTERNAL_SERVER_ERROR, "import_failed", exc)

    def _handle_epic_oauth_callback(self) -> None:
        from shared.server_epic_oauth import handle_epic_oauth_callback

        handle_epic_oauth_callback(self)

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
        from shared.supabase_auth import auth_enabled

        run_id = run_id.strip("/").split("/", 1)[0].split("?", 1)[0]
        since = _stream_resume_since(self)
        ticket = _stream_ticket_from_handler(self)
        if auth_enabled():
            profile_id = _peek_stream_ticket(ticket, run_id)
            if not profile_id:
                _send_auth_required(self)
                return
            set_request_profile_id(profile_id)

        run, terminal = _wait_for_stream_target(run_id, since=since)
        if run is None and terminal is None:
            self.send_error(HTTPStatus.NOT_FOUND, "Unknown run id")
            return

        if run is None and terminal is not None:
            with _sse_lock:
                if _sse_connections >= MAX_SSE_CONNECTIONS:
                    _send_json(
                        self,
                        HTTPStatus.SERVICE_UNAVAILABLE,
                        {"error": f"too many stream connections (max {MAX_SSE_CONNECTIONS})"},
                    )
                    return
                _sse_connections += 1
            if auth_enabled() and not _commit_stream_ticket(ticket, run_id):
                with _sse_lock:
                    _sse_connections = max(0, _sse_connections - 1)
                _send_auth_required(self)
                return
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

        if auth_enabled() and not _commit_stream_ticket(ticket, run_id):
            with _sse_lock:
                _sse_connections = max(0, _sse_connections - 1)
            _send_auth_required(self)
            return

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


def _start_background_scheduler() -> None:
    """Start the pro-tier background refresh scheduler (best-effort)."""
    global SCHEDULER
    try:
        from scheduler import BackgroundScheduler

        SCHEDULER = BackgroundScheduler(
            manager=MANAGER,
            fetchers=FETCHERS,
            missing_requirements=lambda reqs: _missing_requirements(reqs),
        )
        SCHEDULER.start()
    except Exception as exc:  # noqa: BLE001 - scheduler must never block server boot
        print(f"[scheduler] not started: {exc!r}", file=sys.stderr, flush=True)


def _start_idle_shutdown_watchdog() -> None:
    """Self-exit after a no-activity window so abandoned dev servers don't pile
    up. Default 30 min in dev; off for frozen builds (a tester's minimized app
    must stay resident) unless BAKLOG_IDLE_SHUTDOWN_MINUTES is set (0 disables)."""
    raw = os.environ.get("BAKLOG_IDLE_SHUTDOWN_MINUTES")
    if raw is None:
        minutes = 0.0 if is_frozen() else 30.0
    else:
        try:
            minutes = max(0.0, float(raw))
        except ValueError:
            minutes = 0.0
    _start_idle_watchdog(minutes * 60.0, _server_is_idle_ok, _trigger_dev_shutdown)


def _shutdown_server() -> None:
    if SCHEDULER is not None:
        SCHEDULER.stop()
    MANAGER.shutdown()


def _trigger_dev_shutdown() -> None:
    """Graceful shutdown for tray quit / POST /api/shutdown."""
    _shutdown_server()
    httpd = _DEV_HTTPD
    if httpd is not None:
        try:
            httpd.shutdown()
        except OSError:
            pass


def _maybe_import_legacy_env() -> None:
    """One-time: migrate root .env into encrypted storage, then delete .env."""
    from shared.legacy_env import maybe_import_legacy_env
    from shared.profile_paths import DEFAULT_PROFILE_ID

    count, err = maybe_import_legacy_env(ROOT)
    if err:
        print(f"[auth] .env import skipped: {err}", file=sys.stderr, flush=True)
    elif count:
        print(
            f"[auth] Imported {count} provider(s) from .env into profile "
            f"'{DEFAULT_PROFILE_ID}' (plaintext credentials removed from .env)",
            flush=True,
        )


# Records the PID of the live dev server so a restart can reclaim the port if a
# previous instance was orphaned (e.g. the terminal window was closed instead of
# Ctrl+C, so graceful shutdown never ran and the listener kept holding the port).
# Single-instance reclaim + stale-pid self-heal live in shared/dev_server_pids.py.
PID_FILE = ROOT / ".baklog_server.pid"


def _server_is_idle_ok() -> bool:
    """True when it is safe to self-exit on idle: no in-flight fetcher runs and
    no active browser sign-in, so a long fetch or CDP login is never cut off."""
    try:
        if MANAGER._in_flight_targets():
            return False
        from auth.manager import has_active_sessions

        if has_active_sessions():
            return False
    except Exception:  # noqa: BLE001 - a probe error must not trigger an exit
        return False
    return True


class BaklogDevServer(ThreadingHTTPServer):
    allow_reuse_address = False


def _app_version() -> str:
    try:
        import tomllib

        raw = (bundle_root() / "pyproject.toml").read_text(encoding="utf-8")
        return str(tomllib.loads(raw).get("project", {}).get("version", "0.0.0"))
    except Exception:
        return "0.0.0"


def _chromium_available() -> bool:
    try:
        from auth.cdp_browser import find_chromium_executable

        find_chromium_executable()
        return True
    except Exception:
        return False


def _check_data_dir_writable() -> None:
    """Fail fast with a clear message if the data dir is read-only (e.g. a frozen
    build unzipped into Program Files). Testers unzip portable builds; a read-only
    location otherwise produces confusing silent write failures later."""
    target = ROOT
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe = target / ".baklog_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError:
        msg = (
            f"BAKLOG cannot write to its data folder:\n  {target}\n"
            "On Windows the default is %LOCALAPPDATA%\\BAKLOG-Data. "
            "Move BAKLOG to a writable location or set BAKLOG_DATA_DIR."
        )
        print(msg, file=sys.stderr, flush=True)
        raise SystemExit(1) from None


def _maybe_open_browser() -> None:
    if os.environ.get("BAKLOG_NO_BROWSER", "").strip().lower() in ("1", "true", "yes"):
        return
    if not is_frozen():
        return
    try:
        import webbrowser

        webbrowser.open(f"http://{HOST}:{PORT}/")
    except Exception:
        pass


def _frozen_pause_before_exit(code: int = 1) -> None:
    if not is_frozen() or code == 0:
        return
    try:
        input("Press Enter to close...")
    except EOFError:
        pass


def main() -> None:
    global _DEV_HTTPD
    atexit.register(_shutdown_server)
    atexit.register(lambda: _remove_own_pid_file(PID_FILE))
    _maybe_import_legacy_env()
    try:
        from shared.profile_paths import reconcile_profile_store
        from shared.profiles import finalize_default_profile_migration

        finalize_default_profile_migration()
        for note in reconcile_profile_store():
            print(f"[profiles] {note}", file=sys.stderr, flush=True)
        from auth.manager import migrate_existing_itch_local_opt_in

        for note in migrate_existing_itch_local_opt_in():
            print(f"[auth] {note}", file=sys.stderr, flush=True)
    except Exception as exc:  # noqa: BLE001 - must not block server boot
        print(f"[profiles] profile store reconcile skipped: {exc}", file=sys.stderr, flush=True)

    def _handle_exit(signum: int, _frame: Any) -> None:
        print(f"\nShutting down (signal {signum}).")
        _shutdown_server()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, _handle_exit)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_exit)

    _check_data_dir_writable()
    from shared.server_support import run_boot_checks

    run_boot_checks(ROOT)
    _reclaim_or_exit(HOST, PORT, PID_FILE, _DEV_SERVER_BUSY_MSG)
    MANAGER._reap_orphan_processes()
    _start_background_scheduler()
    _start_idle_shutdown_watchdog()
    handler = partial(Handler, directory=str(static_root()))
    try:
        httpd = BaklogDevServer((HOST, PORT), handler)
    except OSError:
        print(_DEV_SERVER_BUSY_MSG, file=sys.stderr, flush=True)
        raise SystemExit(1) from None
    _DEV_HTTPD = httpd
    with httpd:
        _write_pid_file_impl(PID_FILE)
        MANAGER._restore_durable_queue()  # primary server only; after port bind
        print(f"BAKLOG dev server on http://{HOST}:{PORT}")
        if serve_built_frontend():
            if is_frozen():
                print("Frontend: built dist/ assets (immutable cache on hashed files)")
            else:
                print(
                    "Frontend: built dist/ JS + live source CSS "
                    "(no cache — reload picks up app.css edits)"
                )
            _warn_built_manifest_version_mismatch()
        else:
            print("Frontend: raw ESM (set BAKLOG_SERVE_BUILT=1 after npm run build)")
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
        if not _chromium_available():
            print(
                "NOTE: Google Chrome or Microsoft Edge is required for Connections sign-in.",
                flush=True,
            )
        _maybe_open_browser()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down.")


if __name__ == "__main__":
    # Fetcher-child dispatch happens at the top of this module (before any
    # server/RunManager state is built); reaching here means server mode.
    try:
        main()
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else (1 if exc.code else 0)
        if code:
            _frozen_pause_before_exit(code)
        raise
    except Exception as exc:
        print(f"\nBAKLOG failed to start: {exc}", file=sys.stderr, flush=True)
        _frozen_pause_before_exit(1)
        raise SystemExit(1) from exc
