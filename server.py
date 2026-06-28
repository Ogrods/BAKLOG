import atexit
import json

__all__ = ["_pid_alive", "personal_path", "_load_run_history_from", "Run", "popen_fetcher"]
import os
import queue
import secrets
import signal
import subprocess
import sys
import threading
import time
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from shared.built_frontend import is_immutable_built_asset as _is_immutable_built_asset
from shared.built_frontend import maybe_serve_built_index as _maybe_serve_built_index
from shared.dev_server_pids import pid_alive as _pid_alive
from shared.dev_server_pids import reclaim_or_exit as _reclaim_or_exit
from shared.dev_server_pids import remove_own_pid_file as _remove_own_pid_file
from shared.dev_server_pids import terminate_pid as _terminate_pid_impl
from shared.dev_server_pids import write_pid_file as _write_pid_file_impl
from shared.idle_watchdog import note_activity as _note_activity
from shared.idle_watchdog import start_idle_watchdog as _start_idle_watchdog
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


def _warn_built_manifest_version_mismatch():
    if not serve_built_frontend():
        return
    manifest = load_built_manifest()
    built_ver = str(manifest.get("version") or "").strip()
    app_ver = _app_version()
    if built_ver and built_ver != app_ver:
        print(
            f"WARNING: dist/manifest.json version {built_ver} != app {app_ver} — run npm run build before testing packaged frontend",
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
FREE_CLAIMS_INPUT_PATH = Path(os.environ.get("BAKLOG_FREE_CLAIMS_INPUT", "free-claims.input.json"))
FREE_CLAIMS_AUTO_PATH = Path("curated/free_claims.auto.json")
FREE_CLAIMS_APPROVED_PATH = Path("curated/free_claims.approved.json")
FREE_CLAIMS_BUILT_PATH = Path("landing/free-claims.json")
SPONSORS_PATH = Path(os.environ.get("BAKLOG_SPONSORS_INPUT", "curated/sponsors.json"))
INTERNAL_JOBS_OVERLAY = bundle_root() / "admin" / "admin-jobs.json"
MAX_ADMIN_CLAIM_ITEMS = int(os.environ.get("BAKLOG_MAX_ADMIN_CLAIM_ITEMS", "500"))
MAX_ADMIN_ENRICH_BATCH = int(os.environ.get("BAKLOG_MAX_ADMIN_ENRICH_BATCH", "64"))
_DEV_SERVER_BUSY_MSG = (
    f"BAKLOG dev server is already running on http://{HOST}:{PORT} — stop that instance first (it owns the port)."
)
MAX_HISTORY = 200
MAX_LINES_PER_RUN = 25000
MAX_SSE_CONNECTIONS = 8
STALL_FIRST_NOTICE_SEC = 60
STALL_REPEAT_SEC = 60
STALL_POLL_SEC = 1.0
SILENT_STALL_KILL_SEC = 180
TERMINATE_GRACE_SEC = 5
CANCEL_STUCK_GRACE_SEC = TERMINATE_GRACE_SEC + 2
WATCHDOG_INTERVAL_SEC = 3.0
SWITCH_CANCEL_WAIT_SEC = 2 * TERMINATE_GRACE_SEC
LAUNCH_TIMEOUT_SEC = 30
STUCK_NO_PROC_GRACE_SEC = LAUNCH_TIMEOUT_SEC + 15
_runs_file_lock = threading.Lock()
_IN_FLIGHT_STATUSES = frozenset({"queued", "launching", "running", "cancelling"})
_sse_connections = 0
_sse_lock = threading.Lock()
_BAKLOG_LOCAL_HEADER = "X-BAKLOG-Local"
_LOCAL_HOSTNAMES = frozenset({"127.0.0.1", "localhost", "::1"})
from shared.log_redact import (
    redact_diagnostics_payload as _redact_diagnostics_payload,
)
from shared.log_redact import (
    redact_log_line as _redact_log_line,
)
from shared.server_epic_oauth import register_epic_oauth_state as _register_epic_oauth_state
from shared.server_stream_tickets import (
    STREAM_ATTACH_LONG_WAIT_SEC as _STREAM_ATTACH_LONG_WAIT_SEC,
)
from shared.server_stream_tickets import (
    STREAM_ATTACH_POLL_SEC as _STREAM_ATTACH_POLL_SEC,
)
from shared.server_stream_tickets import (
    STREAM_ATTACH_SHORT_WAIT_SEC as _STREAM_ATTACH_SHORT_WAIT_SEC,
)
from shared.server_stream_tickets import (
    commit_stream_ticket as _commit_stream_ticket,
)
from shared.server_stream_tickets import (
    consume_stream_ticket as _consume_stream_ticket,
)
from shared.server_stream_tickets import (
    mint_stream_ticket as _mint_stream_ticket,
)
from shared.server_stream_tickets import (
    peek_stream_ticket as _peek_stream_ticket,
)
from shared.server_stream_tickets import (
    stream_ticket_from_handler as _stream_ticket_from_handler,
)


def _authorize_stream(handler):
    from shared.supabase_auth import auth_enabled

    if not auth_enabled():
        return True
    profile_id = _consume_stream_ticket(_stream_ticket_from_handler(handler))
    if not profile_id:
        _send_auth_required(handler)
        return False
    set_request_profile_id(profile_id)
    return True


from shared import server_auth_secrets, server_internal_routes
from shared.platform_support import platform_supported
from shared.profile_paths import (
    PROFILE_CACHE_JSON_FILES,
    cache_json_path,
    catalog_path,
    clear_request_profile_id,
    free_claims_path,
    get_active_profile_id,
    personal_backup_dir,
    personal_path,
    profile_root,
    runs_dir,
    set_request_profile_id,
    sponsors_path,
)
from shared.server_personal import BAKLOG_ALLOW_EMPTY_HEADER as _BAKLOG_ALLOW_EMPTY_HEADER
from shared.server_personal import PERSONAL_MAX_BYTES, PersonalCorruptError, PersonalEmptyOverwriteError
from shared.server_personal import load_personal_doc as _load_personal_doc
from shared.server_personal import save_personal_doc as _save_personal_doc
from shared.server_static import LIBRARY_JSON_RE as _LIBRARY_JSON_RE
from shared.server_static import normalize_static_path as _normalize_static_path
from shared.server_static import resolved_static_path_allowed as _resolved_static_path_allowed
from shared.server_static import static_class as _static_class_impl
from shared.subprocess_guard import _max_run_seconds_from_env, popen_fetcher

MAX_RUN_SECONDS = _max_run_seconds_from_env()


def _max_run_seconds_for_key(key):
    spec = FETCHERS.get(key) or INTERNAL_JOBS.get(key) or {}
    override = spec.get("maxRunSeconds")
    try:
        value = float(override) if override is not None else None
    except (TypeError, ValueError):
        value = None
    if value is None:
        return MAX_RUN_SECONDS
    return float("inf") if value <= 0 else max(60.0, value)


def _release_server_profile_env():
    return os.environ.pop("BAKLOG_PROFILE", "").strip() or None


_SERVER_ENV_PROFILE_OVERRIDE = _release_server_profile_env()
RUNS_DIR = runs_dir()
ACTIVE_RUNS_FILE = RUNS_DIR / "active.json"
RUN_HISTORY_FILE = RUNS_DIR / "history.json"
QUEUE_FILE = RUNS_DIR / "queue.json"
PERSONAL_BACKUP_DIR = personal_backup_dir()


def _refresh_personal_paths():
    global PERSONAL_BACKUP_DIR
    global RUNS_DIR, ACTIVE_RUNS_FILE, RUN_HISTORY_FILE, QUEUE_FILE
    PERSONAL_BACKUP_DIR = personal_backup_dir()
    RUNS_DIR = runs_dir()
    ACTIVE_RUNS_FILE = RUNS_DIR / "active.json"
    RUN_HISTORY_FILE = RUNS_DIR / "history.json"
    QUEUE_FILE = RUNS_DIR / "queue.json"
    MANAGER.rebind_profile_paths()
    try:
        import auth.secrets as _secrets

        _secrets.reset_cache()
    except Exception:
        pass


def _argv(*parts):
    return [_python_executable(), *parts]


def _fetcher_argv(key, script, extra_args):
    if is_frozen():
        return _argv("--run-fetcher", key, *map(str, extra_args))
    return _argv(str(bundle_root() / script), *map(str, extra_args))


def _fetcher_cmd_label(argv):
    if len(argv) > 2 and argv[1] == "--run-fetcher":
        return " ".join([argv[2], *argv[3:]])
    if len(argv) > 1:
        return " ".join([Path(argv[1]).name, *argv[2:]])
    return ""


def _python_executable():
    if is_frozen():
        return sys.executable
    override = os.environ.get("BAKLOG_PYTHON", "").strip()
    if override:
        return override
    candidates = [
        ROOT / ".venv" / "Scripts" / "python.exe",
        ROOT / ".venv" / "bin" / "python",
        ROOT / ".venv" / "bin" / "python3",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    exe = sys.executable
    if sys.platform != "win32":
        return exe
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


def _load_fetchers():
    try:
        from fetchers.registry import MANIFEST_PATH
    except ImportError as exc:
        print(f"[fetchers] registry import failed: {exc!r}", file=sys.stderr)
        return {}
    try:
        from fetchers.registry import validate_manifest

        for err in validate_manifest(MANIFEST_PATH):
            print(f"[fetchers] manifest: {err}", file=sys.stderr)
    except Exception as exc:
        print(f"[fetchers] manifest validation skipped: {exc!r}", file=sys.stderr)
    try:
        raw = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        entries = raw.get("fetchers", [])
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[fetchers] manifest load failed: {exc!r}", file=sys.stderr)
        entries = []
    fetchers = {}
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
                if max_run_seconds > 0:
                    max_run_seconds = max(60.0, max_run_seconds)
        fetchers[key] = {
            "label": label,
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


def _missing_requirements(requires):
    missing = []
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


FETCHERS = _load_fetchers()
_DEFAULT_INTERNAL_JOBS = {
    "claimSources": {
        "label": "Fetch claim sources",
        "script": "fetchers/fetch_claim_sources.py",
        "group": "claims",
        "description": "Auto-discover free claims from Epic, GamerPower, and ITAD giveaways RSS",
        "args": [],
        "options": {
            "--dry-run": {"type": "bool", "default": False},
            "--source": {"type": "enum", "values": ["all", "epic", "gamerpower", "itad"], "default": "all"},
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
            "--require-manual-approval": {"type": "bool", "default": False},
        },
    },
}


def _script_under_bundle(script):
    rel = str(script or "").strip().replace("\\", "/").lstrip("/")
    if not rel or ".." in rel.split("/") or (not rel.endswith(".py")):
        return False
    root = bundle_root().resolve()
    try:
        target = (root / rel).resolve()
        target.relative_to(root)
        return target.is_file()
    except (OSError, ValueError):
        return False


def _normalize_internal_job_entry(raw):
    key = str(raw.get("key") or "").strip()
    script = str(raw.get("script") or "").strip()
    if not key or not script or (not _script_under_bundle(script)):
        return None
    args = raw.get("args") or []
    if not isinstance(args, list):
        args = []
    options = raw.get("options") or {}
    if not isinstance(options, dict):
        options = {}
    return (
        key,
        {
            "label": str(raw.get("label") or key),
            "script": script,
            "group": str(raw.get("group") or "internal"),
            "description": str(raw.get("description") or ""),
            "args": [str(a) for a in args],
            "options": options,
        },
    )


def _load_internal_jobs():
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
                    print(f"[internal] skipping job {key}: collides with fetcher key", file=sys.stderr)
                    continue
                jobs[key] = entry
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[internal] admin-jobs.json load failed: {exc!r}", file=sys.stderr)
    for key in list(jobs):
        if key in FETCHERS:
            print(f"[internal] built-in job {key} collides with fetcher key — omitting", file=sys.stderr)
            del jobs[key]
    return jobs


def _internal_job_argv(spec, extra_args):
    base = spec.get("args") or []
    script = str(spec.get("script") or "").strip()
    if not _script_under_bundle(script):
        raise ValueError(f"invalid internal job script: {script!r}")
    return _argv(str(bundle_root() / script), *base, *extra_args)


def _coerce_bool(value):
    if isinstance(value, bool):
        return value
    if value in (1, "1", "true", "True", "yes", "on"):
        return True
    if value in (0, "0", "false", "False", "no", "off", None, ""):
        return False
    raise ValueError(f"invalid boolean value: {value!r}")


def validate_internal_args(spec, args):
    options = spec.get("options") or {}
    extra = []
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


def _resolve_contained_data_path(rel):
    root = data_root().resolve()
    try:
        target = (root / rel).resolve()
        target.relative_to(root)
        return target
    except (OSError, ValueError):
        return None


def _admin_list_too_large(items, *, cap, label):
    if len(items) > cap:
        return f"{label} exceeds maximum of {cap} items"
    return None


def _is_internal_admin_path(path):
    return path.startswith("/api/internal/")


def _read_optional_json(path):
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


INTERNAL_JOBS = _load_internal_jobs()
from shared.run_manager import Run, RunManager, _load_run_history, _load_run_history_from, _run_id_active_on_disk

MANAGER = RunManager(restore_durable=False)


def _terminate_pid(pid):
    _terminate_pid_impl(pid)


def _kill_pids_async(pids):
    unique = list(dict.fromkeys((p for p in pids if p > 0)))
    if not unique:
        return

    def _work():
        for pid in unique:
            _terminate_pid(pid)

    threading.Thread(target=_work, name="run-kill", daemon=True).start()


SCHEDULER = None
_DEV_HTTPD = None


def _header_hostname(value):
    if not value:
        return None
    host = (urlparse(value).hostname or "").lower()
    return host or None


def _normalize_host(raw):
    if not raw:
        return ""
    host = raw.strip()
    if host.startswith("["):
        end = host.find("]")
        return (host[1:end] if end != -1 else host[1:]).lower()
    if host.count(":") > 1:
        return host.lower()
    return host.split(":", 1)[0].lower()


def _request_host_is_local(handler):
    return _normalize_host(handler.headers.get("Host", "")) in _LOCAL_HOSTNAMES


def _origin_is_local(handler):
    for name in ("Origin", "Referer"):
        host = _header_hostname(handler.headers.get(name))
        if host in _LOCAL_HOSTNAMES:
            return True
    return False


def _csrf_allowed(handler):
    from shared.supabase_auth import auth_enabled, verify_bearer_user

    if auth_enabled() and verify_bearer_user(handler.headers.get("Authorization")):
        return True
    if not _request_host_is_local(handler):
        return False
    if handler.headers.get(_BAKLOG_LOCAL_HEADER) == "1":
        return True
    return _origin_is_local(handler)


def _csrf_allowed_strict(handler):
    from shared.supabase_auth import auth_enabled, verify_bearer_user

    if auth_enabled() and verify_bearer_user(handler.headers.get("Authorization")):
        return True
    if not _request_host_is_local(handler):
        return False
    return handler.headers.get(_BAKLOG_LOCAL_HEADER) == "1"


def _send_json(handler, status, payload):
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def _send_bytes(handler, status, body, *, content_type, filename=None):
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    if filename:
        handler.send_header("Content-Disposition", f'attachment; filename="{filename}"')
    handler.end_headers()
    handler.wfile.write(body)


def _sse_format(event, data, *, event_id=None):
    payload = data if isinstance(data, str) else json.dumps(data)
    parts = []
    if event_id is not None:
        parts.append(f"id: {event_id}")
    parts.append(f"event: {event}")
    parts.append(f"data: {payload}")
    parts.append("")
    return ("\n".join(parts) + "\n").encode("utf-8")


def _stream_resume_since(handler):
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


def _static_class(path_only):
    return _static_class_impl(path_only, admin_enabled=ADMIN_ENABLED)


def _path_only(handler):
    return handler.path.split("?", 1)[0]


def _send_auth_required(handler):
    if handler.command.upper() == "HEAD":
        handler.send_response(HTTPStatus.UNAUTHORIZED)
        handler.end_headers()
    else:
        _send_json(handler, HTTPStatus.UNAUTHORIZED, {"error": "sign in required"})


def _bind_request_user(handler):
    from shared.account_profiles import ensure_profile_for_user
    from shared.supabase_auth import local_profiles_enabled, verify_bearer_user

    user = verify_bearer_user(handler.headers.get("Authorization"))
    if not user:
        _send_auth_required(handler)
        return None
    if local_profiles_enabled():
        return user["id"]
    pid = ensure_profile_for_user(user["id"], user.get("email") or None)
    set_request_profile_id(pid)
    return pid


def _bind_bearer_profile(handler):
    return _bind_request_user(handler) is not None


def _gate_static(handler):
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


def _maybe_serve_empty_library_json(handler, path):
    if not _LIBRARY_JSON_RE.match(path):
        return False
    filename = path.lstrip("/")
    if catalog_path(filename).is_file():
        return False
    _send_json(handler, HTTPStatus.OK, {"game_count": 0, "games": []})
    return True


def _maybe_serve_empty_claims_json(handler, path):
    if path.lower() != "/free_claims.json":
        return False
    if free_claims_path().is_file():
        return False
    _send_json(handler, HTTPStatus.OK, {"generated_at": None, "items": []})
    return True


def _maybe_serve_empty_sponsors_json(handler, path):
    if path.lower() != "/sponsors.json":
        return False
    if sponsors_path().is_file():
        return False
    _send_json(handler, HTTPStatus.OK, {"version": 1, "generated_at": None, "items": []})
    return True


_EMPTY_CACHE_META_JSON = {
    "hltb_map.json": {"fetched_at": None},
    "steam_review_map.json": {"fetched_at": None},
    "cross_store_images_meta.json": {"fetched_at": None, "no_steam_match": []},
    "steam_tags_meta.json": {"fetched_at": None},
    "protondb_map.json": {"fetched_at": None},
    "fx_rates.json": {"fetched_at": None, "rates": {}},
}


def _maybe_serve_empty_cache_meta_json(handler, path):
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


def _read_json_body(handler, *, max_bytes=PERSONAL_MAX_BYTES):
    try:
        length = int(handler.headers.get("Content-Length") or 0)
    except ValueError:
        return (None, "invalid Content-Length")
    if length <= 0:
        return (None, "empty body")
    if length > max_bytes:
        return (None, f"body too large ({length} > {max_bytes})")
    try:
        raw = handler.rfile.read(length).decode("utf-8")
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return (None, f"invalid JSON: {exc!r}")
    if not isinstance(payload, dict):
        return (None, "payload must be a JSON object")
    return (payload, None)


_AUTH_JSON_MAX_BYTES = 64 * 1024
_SECRETS_IMPORT_MAX_BYTES = 160 * 1024 * 1024


def _api_error(handler, status, code, exc=None):
    if exc is not None:
        try:
            detail = _redact_log_line(f"{type(exc).__name__}: {exc}")
        except Exception:
            detail = type(exc).__name__
        print(f"[api] {code}: {detail}", file=sys.stderr, flush=True)
    _send_json(handler, status, {"error": code})


def _api_path(handler):
    raw = handler.path.split("?", 1)[0]
    return raw.rstrip("/") or "/"


def _require_api_auth(handler):
    from shared.supabase_auth import auth_enabled

    path = _api_path(handler)
    if not path.startswith("/api/"):
        return True
    if path in (
        "/api/config",
        "/api/update-check",
        "/api/update/status",
        "/api/update/apply-result",
        "/api/diagnostics",
    ):
        return True
    if ADMIN_ENABLED and _is_admin_exempt_api(path):
        return True
    if not auth_enabled():
        return True
    return _bind_request_user(handler) is not None


def _is_admin_exempt_api(path):
    if path.startswith("/api/internal/"):
        return True
    if path == "/api/runs" or path.startswith("/api/runs/"):
        return True
    if path.startswith("/api/run/"):
        return True
    if path.startswith("/api/stream/"):
        return True
    return False


def _profile_admin_blocked():
    from shared.supabase_auth import auth_enabled, local_profiles_enabled

    return auth_enabled() and (not local_profiles_enabled())


def _profile_run_isolation_enabled():
    from shared.supabase_auth import auth_enabled

    if auth_enabled():
        return True
    from shared.profile_paths import list_profiles

    return len(list_profiles()) > 1


def _run_accessible(run):
    if run is None:
        return None
    if not _profile_run_isolation_enabled():
        return run
    if run.profile_id == get_active_profile_id():
        return run
    return None


def _stream_terminal_accessible(run_id):
    terminal = MANAGER.stream_terminal_summary(run_id)
    if terminal is None:
        return None
    if _profile_run_isolation_enabled() and terminal.get("profile_id") != get_active_profile_id():
        return None
    return terminal


def _resolve_stream_target(run_id):
    run = _run_accessible(MANAGER.get(run_id))
    if run is not None:
        return (run, None)
    return (None, _stream_terminal_accessible(run_id))


def _wait_for_stream_target(run_id, *, since):
    run, terminal = _resolve_stream_target(run_id)
    if run is not None or terminal is not None or since > 0:
        return (run, terminal)
    short_deadline = time.time() + _STREAM_ATTACH_SHORT_WAIT_SEC
    while time.time() < short_deadline:
        run, terminal = _resolve_stream_target(run_id)
        if run is not None or terminal is not None:
            return (run, terminal)
        time.sleep(_STREAM_ATTACH_POLL_SEC)
    if not _run_id_active_on_disk(run_id):
        return (None, None)
    long_deadline = time.time() + _STREAM_ATTACH_LONG_WAIT_SEC
    while time.time() < long_deadline:
        run, terminal = _resolve_stream_target(run_id)
        if run is not None or terminal is not None:
            return (run, terminal)
        time.sleep(_STREAM_ATTACH_POLL_SEC)
    return (None, None)


class Handler(SimpleHTTPRequestHandler):
    def handle_one_request(self):
        _note_activity()
        super().handle_one_request()

    def handle(self):
        try:
            super().handle()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass
        finally:
            clear_request_profile_id()

    def _reject_if_csrf(self):
        if _csrf_allowed(self):
            return False
        _send_json(
            self,
            HTTPStatus.FORBIDDEN,
            {"error": "cross-origin request blocked — open BAKLOG from http://127.0.0.1 and retry"},
        )
        return True

    def _reject_if_csrf_strict(self):
        if _csrf_allowed_strict(self):
            return False
        _send_json(
            self,
            HTTPStatus.FORBIDDEN,
            {"error": "cross-origin request blocked — open BAKLOG from http://127.0.0.1 and retry"},
        )
        return True

    server_version = "SteamBacklogDev/1.0"
    _NO_CACHE_SUFFIXES = (".js", ".mjs", ".css", ".html")

    def end_headers(self):
        path = self.path.split("?", 1)[0]
        path_lower = path.lower()
        if is_frozen() and serve_built_frontend() and _is_immutable_built_asset(path):
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        elif path_lower.endswith(self._NO_CACHE_SUFFIXES) or path_lower in ("/", ""):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def translate_path(self, path):
        norm = _normalize_static_path(path.split("?", 1)[0])
        clean = norm.lstrip("/")
        if _static_class(norm) == "deny":
            return str(profile_root() / ".profile_static_blocked" / clean)
        if clean.startswith("profiles/"):
            return str(profile_root() / ".profile_static_blocked" / clean)
        if _LIBRARY_JSON_RE.match(norm) or norm.lower() in ("/itad_prices.json", "/free_claims.json", "/sponsors.json"):
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
                resolved = str(cache_json_path(name))
                if _resolved_static_path_allowed(resolved):
                    return resolved
                return str(profile_root() / ".profile_static_blocked" / clean)
        resolved = super().translate_path(path)
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

    def _begin_request(self):
        clear_request_profile_id()

    def do_GET(self):
        self._begin_request()
        path = _api_path(self)
        if path == "/api/config":
            self._handle_config_get()
            return
        if path in ("/api/update-check", "/api/update/status", "/api/update/apply-result", "/api/diagnostics"):
            self._handle_support_get(path)
            return
        if path.startswith("/oauth/epic/callback"):
            self._handle_epic_oauth_callback()
            return
        if path.startswith("/api/stream/"):
            self._handle_stream(path[len("/api/stream/") :])
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
        if path == "/api/mirror":
            from shared.server_mirror import handle_mirror_get

            handle_mirror_get(self)
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

    def do_HEAD(self):
        self._begin_request()
        if _api_path(self) == "/api/config":
            self._handle_config_get()
            return
        if not _require_api_auth(self):
            return
        if not _gate_static(self):
            return
        super().do_HEAD()

    def do_POST(self):
        self._begin_request()
        path = _api_path(self)
        if path == "/api/shutdown":
            if self._reject_if_csrf_strict():
                return
            self._handle_shutdown()
            return
        if path in (
            "/api/update/download",
            "/api/update/cancel",
            "/api/update/apply",
            "/api/update/discard-ready",
            "/api/update/dismiss",
        ):
            if self._reject_if_csrf_strict():
                return
            self._handle_update_post(path)
            return
        if _is_internal_admin_path(path):
            if self._reject_if_csrf_strict():
                return
        elif self._reject_if_csrf_strict():
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

            if (
                auth_enabled()
                and ADMIN_ENABLED
                and (verify_bearer_user(self.headers.get("Authorization")) is None)
                and _request_host_is_local(self)
                and (self.headers.get(_BAKLOG_LOCAL_HEADER) == "1")
            ):
                self._handle_stream_ticket_mint()
                return
        if path == "/api/auth/sign-out":
            from shared.server_auth_sign_out import handle_auth_sign_out_post

            handle_auth_sign_out_post(self)
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
            rest = path[len("/api/run/") :].strip("/")
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
        if path in (
            "/api/auth/master-password",
            "/api/auth/secrets/export",
            "/api/auth/secrets/reset",
        ) or path.startswith("/api/auth/secrets/import"):
            if self._reject_if_csrf_strict():
                return
        if path == "/api/auth/master-password":
            self._handle_auth_master_password()
            return
        if path == "/api/auth/secrets/export":
            server_auth_secrets.handle_auth_secrets_export(self)
            return
        if path.startswith("/api/auth/secrets/import"):
            self._handle_auth_secrets_import()
            return
        if path == "/api/auth/secrets/reset":
            server_auth_secrets.handle_auth_secrets_reset(self)
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
        if path == "/api/mirror/import":
            if self._reject_if_csrf_strict():
                return
            from shared.server_mirror import handle_mirror_import_post

            handle_mirror_import_post(self)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")

    def do_DELETE(self):
        self._begin_request()
        if self._reject_if_csrf_strict():
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

    def do_PUT(self):
        self._begin_request()
        path = _api_path(self)
        if _is_internal_admin_path(path):
            if self._reject_if_csrf_strict():
                return
        elif self._reject_if_csrf_strict():
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
        if path == "/api/pro-settings":
            if self._reject_if_csrf_strict():
                return
            from shared.server_pro_settings import handle_pro_settings_put

            handle_pro_settings_put(self)
            return
        if path.startswith("/api/profiles/"):
            if self._reject_if_csrf_strict():
                return
            profile_id = path[len("/api/profiles/") :].strip("/")
            if profile_id and profile_id not in ("active", "pin") and (not profile_id.endswith("/pin")):
                self._handle_profiles_rename(profile_id)
                return
        if path.startswith("/api/auth/") and path.endswith("/credentials"):
            provider = path[len("/api/auth/") : -len("/credentials")].strip("/")
            self._handle_auth_credentials(provider)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")

    def _handle_config_get(self):
        from shared.entitlement import current_plan, maybe_refresh_local_license
        from shared.polar_license import polar_configured
        from shared.pro_capabilities import resolve_capabilities
        from shared.pro_checkout import pro_checkout_enabled, public_checkout_urls
        from shared.pro_settings import read_pro_settings
        from shared.supabase_auth import auth_enabled, public_auth_config

        maybe_refresh_local_license()
        config = dict(public_auth_config())
        authorization = self.headers.get("Authorization")
        plan = current_plan(authorization)
        pro_settings = read_pro_settings()
        config["plan"] = plan
        config["capabilities"] = resolve_capabilities(plan=plan, pro_settings=pro_settings)
        config["proSettings"] = pro_settings
        config["licenseActivation"] = polar_configured() and (not auth_enabled())
        config["proCheckoutEnabled"] = pro_checkout_enabled()
        config["proCheckout"] = public_checkout_urls()
        config["frozen"] = is_frozen()
        config["version"] = _app_version()
        config["chromium_available"] = _chromium_available()
        from shared.install_paths import frozen_bundle_dir, is_portable_frozen, runtime_label
        from shared.server_support import is_running_from_temp_dir, redact_user_path

        config["running_from_temp"] = is_frozen() and is_running_from_temp_dir(frozen_bundle_dir())
        config["data_dir_path"] = redact_user_path(ROOT)
        config["runtime_label"] = runtime_label()
        if is_frozen():
            config["portable"] = is_portable_frozen()
        _send_json(self, HTTPStatus.OK, config)

    def _handle_support_get(self, path):
        from auth.manager import has_active_sessions
        from shared.server_support import build_diagnostics_payload
        from shared.update_api import handle_update_support_get

        if handle_update_support_get(
            path,
            current_version=_app_version,
            has_in_flight_runs=lambda: bool(MANAGER._in_flight_targets()),
            has_active_sessions=has_active_sessions,
            send_json=lambda status, payload: _send_json(self, status, payload),
        ):
            return
        _send_json(
            self,
            HTTPStatus.OK,
            _redact_diagnostics_payload(
                build_diagnostics_payload(data_root=ROOT, version=_app_version(), load_run_history=_load_run_history)
            ),
        )

    def _handle_fetchers(self):
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
        except Exception as exc:
            _send_json(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

    @staticmethod
    def _parse_run_submit_path(rest):
        from urllib.parse import parse_qs

        path, _, qs = rest.partition("?")
        key = path.strip("/").split("/", 1)[0]
        params = parse_qs(qs) if qs else {}
        refresh_val = (params.get("refresh") or ["0"])[0].lower()
        refresh = refresh_val in ("1", "true", "yes")
        return (key, refresh)

    def _handle_profiles_get(self):
        try:
            from shared.profiles import profiles_status

            data = profiles_status()
            if _profile_admin_blocked():
                active = get_active_profile_id()
                profiles = data.get("profiles") if isinstance(data.get("profiles"), list) else []
                data["profiles"] = [p for p in profiles if isinstance(p, dict) and p.get("id") == active]
                data["active"] = active
                data["accountAuth"] = True
            _send_json(self, HTTPStatus.OK, data)
        except Exception as exc:
            _api_error(self, HTTPStatus.INTERNAL_SERVER_ERROR, "profiles_get_failed", exc)

    def _handle_profiles_create(self):
        if _profile_admin_blocked():
            _send_json(
                self, HTTPStatus.FORBIDDEN, {"error": "profile management is disabled while account sign-in is enabled"}
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
            _send_json(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"profile create failed: {exc}"})

    def _handle_profiles_set_active(self):
        if _profile_admin_blocked():
            _send_json(
                self, HTTPStatus.FORBIDDEN, {"error": "profile switching is disabled while account sign-in is enabled"}
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
                    _send_json(self, HTTPStatus.UNAUTHORIZED, {"error": "pin_required"})
                    return
                if not verify_profile_pin(profile_id, pin):
                    record_pin_failure(profile_id)
                    _send_json(self, HTTPStatus.UNAUTHORIZED, {"error": "incorrect_pin"})
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

    def _handle_profiles_set_pin(self, profile_id):
        if _profile_admin_blocked():
            _send_json(
                self, HTTPStatus.FORBIDDEN, {"error": "profile management is disabled while account sign-in is enabled"}
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

    def _handle_profiles_clear_pin(self, profile_id):
        if _profile_admin_blocked():
            _send_json(
                self, HTTPStatus.FORBIDDEN, {"error": "profile management is disabled while account sign-in is enabled"}
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

    def _handle_profiles_rename(self, profile_id):
        if _profile_admin_blocked():
            _send_json(
                self, HTTPStatus.FORBIDDEN, {"error": "profile management is disabled while account sign-in is enabled"}
            )
            return
        payload, err = _read_json_body(self)
        if err:
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": err})
            return
        assert payload is not None
        try:
            from shared.profiles import rename_profile

            pin = str(payload.get("currentPin") or payload.get("pin") or "").strip() or None
            updated = rename_profile(profile_id, str(payload.get("label") or ""), current_pin=pin)
            _send_json(self, HTTPStatus.OK, updated)
        except ValueError as exc:
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def _handle_profiles_delete(self, profile_id):
        if _profile_admin_blocked():
            _send_json(
                self, HTTPStatus.FORBIDDEN, {"error": "profile management is disabled while account sign-in is enabled"}
            )
            return
        if MANAGER.has_runs_for_profile(profile_id):
            _send_json(
                self,
                HTTPStatus.CONFLICT,
                {
                    "error": "This profile has a fetch running or queued. Cancel its runs or let them finish before deleting."
                },
            )
            return
        current_pin = None
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

    def _handle_personal_get(self):
        try:
            doc = _load_personal_doc()
        except PersonalCorruptError as exc:
            _send_json(self, HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(exc)})
            return
        except Exception as exc:
            _api_error(self, HTTPStatus.INTERNAL_SERVER_ERROR, "personal_load_failed", exc)
            return
        _send_json(self, HTTPStatus.OK, doc)

    def _handle_personal_put(self):
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
                    self, HTTPStatus.CONFLICT, {"error": "profile mismatch", "active": active, "claimed": str(claimed)}
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
        try:
            from shared.cloud_mirror import schedule_mirror_upload
            from shared.profile_paths import personal_path

            schedule_mirror_upload(personal_path())
        except Exception:
            pass
        _send_json(self, HTTPStatus.OK, doc)

    def _handle_runs(self):
        snap = MANAGER.snapshot()
        if _profile_run_isolation_enabled():
            pid = get_active_profile_id()
            active = snap.get("active")
            if active and active.get("profile_id") != pid:
                snap["active"] = None
            snap["queue"] = [r for r in snap.get("queue") or [] if r.get("profile_id") == pid]
            internal_active = snap.get("internal_active")
            if internal_active and internal_active.get("profile_id") != pid:
                snap["internal_active"] = None
            snap["internal_queue"] = [r for r in snap.get("internal_queue") or [] if r.get("profile_id") == pid]
            snap["history"] = [r for r in snap.get("history") or [] if r.get("profile_id") == pid]
        _send_json(self, HTTPStatus.OK, snap)

    def _handle_submit(self, rest):
        key, refresh = self._parse_run_submit_path(rest)
        if key not in FETCHERS:
            _send_json(self, HTTPStatus.NOT_FOUND, {"error": f"unknown fetcher: {key}"})
            return
        fetcher_platforms = FETCHERS[key].get("platforms")
        if not platform_supported(fetcher_platforms):
            allowed = ", ".join(fetcher_platforms or [])
            _send_json(
                self,
                HTTPStatus.BAD_REQUEST,
                {
                    "error": f"{FETCHERS[key]['label']} is only available on {allowed} (this server runs on {sys.platform})."
                },
            )
            return
        if refresh and (not FETCHERS[key].get("refreshArgs")):
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": f"{key} does not support refresh"})
            return
        try:
            run = MANAGER.submit(key, refresh=refresh)
        except ValueError as exc:
            _send_json(self, HTTPStatus.CONFLICT, {"error": str(exc)})
            return
        _send_json(
            self, HTTPStatus.ACCEPTED, {"run_id": run.id, "key": run.key, "label": run.label, "status": run.status}
        )

    def _handle_cancel(self, run_id):
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

    def _handle_cancel_all(self):
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

    def _handle_shutdown(self):
        _send_json(self, HTTPStatus.OK, {"ok": True})
        threading.Thread(target=_trigger_dev_shutdown, name="dev-shutdown", daemon=True).start()

    def _handle_update_post(self, path):
        from auth.manager import has_active_sessions
        from shared.update_api import handle_update_post

        handle_update_post(
            path,
            current_version=_app_version,
            has_in_flight_runs=lambda: bool(MANAGER._in_flight_targets()),
            has_active_sessions=has_active_sessions,
            read_json_body=lambda: _read_json_body(self, max_bytes=4096),
            send_json=lambda status, payload: _send_json(self, status, payload),
            trigger_shutdown=_trigger_dev_shutdown,
        )

    def _handle_license_activate(self):
        from shared.entitlement import activate_local_license_key, current_plan

        payload, err = _read_json_body(self)
        if err:
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": err})
            return
        raw_key = payload.get("key") if isinstance(payload, dict) else ""
        ok, message = activate_local_license_key(str(raw_key or ""))
        status = HTTPStatus.OK if ok else HTTPStatus.BAD_REQUEST
        _send_json(self, status, {"ok": ok, "message": message, "plan": current_plan(None)})

    def _handle_auth_session_get(self):
        from shared.server_auth_session import handle_auth_session_get

        handle_auth_session_get(self)

    def _handle_stream_ticket_mint(self):
        payload, err = _read_json_body(self)
        if err == "empty body":
            payload = {}
        elif err:
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": err})
            return
        assert payload is not None
        run_id = None
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

    def _handle_auth_status(self):
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
        except Exception as exc:
            _api_error(self, HTTPStatus.INTERNAL_SERVER_ERROR, "auth_status_failed", exc)

    def _handle_auth_open_url(self, provider):
        try:
            from auth.manager import open_manual_signin

            result = open_manual_signin(provider)
            _send_json(self, HTTPStatus.OK, result)
        except KeyError:
            _send_json(self, HTTPStatus.NOT_FOUND, {"error": f"unknown provider: {provider}"})
        except ValueError as exc:
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception as exc:
            _api_error(self, HTTPStatus.INTERNAL_SERVER_ERROR, "auth_open_url_failed", exc)

    def _handle_auth_start(self, provider):
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
        except Exception as exc:
            _api_error(self, HTTPStatus.INTERNAL_SERVER_ERROR, "auth_start_failed", exc)

    def _public_callback_url(self, path):
        host = self.headers.get("Host") or f"{HOST}:{PORT}"
        proto = (self.headers.get("X-Forwarded-Proto") or "http").strip().lower()
        if proto not in ("http", "https"):
            proto = "http"
        return f"{proto}://{host}{path}"

    def _handle_epic_oauth_url(self):
        try:
            from clients.epic_client import build_epic_oauth_login_url

            state = secrets.token_urlsafe(24)
            _register_epic_oauth_state(state, profile_id=get_active_profile_id())
            redirect_uri = self._public_callback_url("/oauth/epic/callback")
            url = build_epic_oauth_login_url(redirect_uri, state)
            _send_json(self, HTTPStatus.OK, {"url": url, "state": state})
        except Exception as exc:
            _api_error(self, HTTPStatus.INTERNAL_SERVER_ERROR, "epic_oauth_url_failed", exc)

    def _handle_auth_disconnect(self, provider):
        try:
            from auth.manager import disconnect

            disconnect(provider)
            _send_json(self, HTTPStatus.OK, {"ok": True})
        except KeyError:
            _send_json(self, HTTPStatus.NOT_FOUND, {"error": f"unknown provider: {provider}"})
        except Exception as exc:
            _api_error(self, HTTPStatus.INTERNAL_SERVER_ERROR, "auth_disconnect_failed", exc)

    def _handle_auth_enable(self, provider):
        try:
            from auth.manager import enable_local

            enable_local(provider)
            _send_json(self, HTTPStatus.OK, {"ok": True})
        except KeyError:
            _send_json(self, HTTPStatus.NOT_FOUND, {"error": f"unknown provider: {provider}"})
        except ValueError as exc:
            _send_json(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception as exc:
            _api_error(self, HTTPStatus.INTERNAL_SERVER_ERROR, "auth_enable_failed", exc)

    def _handle_auth_credentials(self, provider):
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
        except Exception as exc:
            _api_error(self, HTTPStatus.INTERNAL_SERVER_ERROR, "credentials_failed", exc)

    def _handle_auth_master_password(self):
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
        except Exception as exc:
            _api_error(self, HTTPStatus.INTERNAL_SERVER_ERROR, "master_password_failed", exc)

    def _handle_auth_secrets_import(self):
        import base64

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
                    blob = base64.b64decode(blob_b64, validate=True)
                except ValueError as exc:
                    raise ValueError("blob is not valid base64") from exc
            else:
                blob = b""
            from auth.bundle import BadMagic, BadPassphrase, BundleTooLarge, UnsupportedVersion, import_bundle

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
        except Exception as exc:
            _api_error(self, HTTPStatus.INTERNAL_SERVER_ERROR, "import_failed", exc)

    def _handle_epic_oauth_callback(self):
        from shared.server_epic_oauth import handle_epic_oauth_callback

        handle_epic_oauth_callback(self)

    def _handle_auth_stream(self, session_id):
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

    def _handle_stream(self, run_id):
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
            if auth_enabled() and (not _commit_stream_ticket(ticket, run_id)):
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
        if auth_enabled() and (not _commit_stream_ticket(ticket, run_id)):
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
            self._sse_write(
                "status",
                {
                    "status": run.status,
                    "started_at": run.started_at,
                    "ended_at": run.ended_at,
                    "exit_code": run.exit_code,
                },
            )
            for msg in replay:
                self._sse_write("line", msg, event_id=msg.get("seq"))
            if already_done:
                self._sse_write(
                    "done",
                    {
                        "status": run.status,
                        "exit_code": run.exit_code,
                        "started_at": run.started_at,
                        "ended_at": run.ended_at,
                    },
                )
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
            pass
        finally:
            run.detach_listener(q)
            with _sse_lock:
                _sse_connections = max(0, _sse_connections - 1)

    def _sse_write(self, event, data, *, event_id=None):
        self._sse_write_raw(_sse_format(event, data, event_id=event_id))

    def _sse_write_raw(self, chunk):
        try:
            self.wfile.write(chunk)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            raise

    def log_message(self, format, *args):
        if "/api/stream/" in self.path:
            return
        super().log_message(format, *args)


def _start_background_scheduler():
    global SCHEDULER
    try:
        from scheduler import BackgroundScheduler

        SCHEDULER = BackgroundScheduler(
            manager=MANAGER, fetchers=FETCHERS, missing_requirements=lambda reqs: _missing_requirements(reqs)
        )
        SCHEDULER.start()
    except Exception as exc:
        print(f"[scheduler] not started: {exc!r}", file=sys.stderr, flush=True)
    try:
        from shared.cloud_mirror import start_flush_worker

        start_flush_worker()
    except Exception as exc:
        print(f"[cloud_mirror] worker not started: {exc!r}", file=sys.stderr, flush=True)


def _start_idle_shutdown_watchdog():
    raw = os.environ.get("BAKLOG_IDLE_SHUTDOWN_MINUTES")
    if raw is None:
        minutes = 0.0 if is_frozen() else 30.0
    else:
        try:
            minutes = max(0.0, float(raw))
        except ValueError:
            minutes = 0.0
    _start_idle_watchdog(minutes * 60.0, _server_is_idle_ok, _trigger_dev_shutdown)


def _shutdown_server():
    if SCHEDULER is not None:
        SCHEDULER.stop()
    MANAGER.shutdown()


def _trigger_dev_shutdown():
    _shutdown_server()
    httpd = _DEV_HTTPD
    if httpd is not None:
        try:
            httpd.shutdown()
        except OSError:
            pass


def _maybe_import_legacy_env():
    from shared.legacy_env import maybe_import_legacy_env
    from shared.profile_paths import DEFAULT_PROFILE_ID

    count, err = maybe_import_legacy_env(ROOT)
    if err:
        print(f"[auth] .env import skipped: {err}", file=sys.stderr, flush=True)
    elif count:
        print(
            f"[auth] Imported {count} provider(s) from .env into profile '{DEFAULT_PROFILE_ID}' (plaintext credentials removed from .env)",
            flush=True,
        )


PID_FILE = ROOT / ".baklog_server.pid"


def _server_is_idle_ok():
    try:
        if MANAGER._in_flight_targets():
            return False
        from auth.manager import has_active_sessions

        if has_active_sessions():
            return False
    except Exception:
        return False
    return True


class BaklogDevServer(ThreadingHTTPServer):
    allow_reuse_address = False


def _app_version():
    try:
        import tomllib

        raw = (bundle_root() / "pyproject.toml").read_text(encoding="utf-8")
        return str(tomllib.loads(raw).get("project", {}).get("version", "0.0.0"))
    except Exception:
        return "0.0.0"


def _chromium_available():
    try:
        from auth.cdp_browser import find_chromium_executable

        find_chromium_executable()
        return True
    except Exception:
        return False


def _check_data_dir_writable():
    target = ROOT
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe = target / ".baklog_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError:
        msg = f"BAKLOG cannot write to its data folder:\n  {target}\nOn Windows the default is %LOCALAPPDATA%\\BAKLOG-Data. Move BAKLOG to a writable location or set BAKLOG_DATA_DIR."
        print(msg, file=sys.stderr, flush=True)
        raise SystemExit(1) from None


def _maybe_open_browser():
    if os.environ.get("BAKLOG_NO_BROWSER", "").strip().lower() in ("1", "true", "yes"):
        return
    if not is_frozen():
        return
    try:
        import webbrowser

        webbrowser.open(f"http://{HOST}:{PORT}/")
    except Exception:
        pass


def _frozen_pause_before_exit(code=1):
    if not is_frozen() or code == 0:
        return
    try:
        input("Press Enter to close...")
    except EOFError:
        pass


def main():
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
    except Exception as exc:
        print(f"[profiles] profile store reconcile skipped: {exc}", file=sys.stderr, flush=True)

    def _handle_exit(signum, _frame):
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
        MANAGER._restore_durable_queue()
        print(f"BAKLOG dev server on http://{HOST}:{PORT}")
        if serve_built_frontend():
            if is_frozen():
                print("Frontend: built dist/ assets (immutable cache on hashed files)")
            else:
                print("Frontend: built dist/ JS + live source CSS (no cache — reload picks up app.css edits)")
            _warn_built_manifest_version_mismatch()
        else:
            print("Frontend: raw ESM (set BAKLOG_SERVE_BUILT=1 after npm run build)")
        print(f"Python for fetchers: {_python_executable()}")
        print(f"Registered fetchers: {len(FETCHERS)}")
        print(f"Run history: {RUN_HISTORY_FILE} (max {MAX_HISTORY})")
        if _SERVER_ENV_PROFILE_OVERRIDE:
            print(
                f"NOTE: BAKLOG_PROFILE={_SERVER_ENV_PROFILE_OVERRIDE!r} was set in the server shell; ignoring it so the profile menu owns the active profile (now {get_active_profile_id()!r}). Per-run fetchers still pin their own profile.",
                flush=True,
            )
        if not _chromium_available():
            print("NOTE: Google Chrome or Microsoft Edge is required for Connections sign-in.", flush=True)
        _maybe_open_browser()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down.")


if __name__ == "__main__":
    try:
        main()
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1 if exc.code else 0
        if code:
            _frozen_pause_before_exit(code)
        raise
    except Exception as exc:
        print(f"\nBAKLOG failed to start: {exc}", file=sys.stderr, flush=True)
        _frozen_pause_before_exit(1)
        raise SystemExit(1) from exc
