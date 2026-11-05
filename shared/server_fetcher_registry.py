"""Fetcher manifest + internal admin job registry (extracted from server.py).

Mechanical move only: argv builders, ``fetchers/manifest.json`` load, and
admin ``admin-jobs.json`` merge. ``server.py`` keeps ``FETCHERS`` /
``INTERNAL_JOBS`` module attrs and thin re-exports for tests and
``shared.run_manager``.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from shared.install_paths import bundle_root, data_root, is_frozen

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


def _venv_search_root() -> Path:
    """Same root as server.ROOT (tests monkeypatch server.ROOT)."""
    mod = sys.modules.get("server")
    if mod is not None:
        root = getattr(mod, "ROOT", None)
        if root is not None:
            return Path(root)
    return data_root()


def _python_executable() -> str:
    """Prefer the project's venv interpreter when present."""
    if is_frozen():
        return sys.executable
    override = os.environ.get("BAKLOG_PYTHON", "").strip()
    if override:
        return override
    root = _venv_search_root()
    candidates = [
        root / ".venv" / "Scripts" / "python.exe",  # Windows
        root / ".venv" / "bin" / "python",  # POSIX
        root / ".venv" / "bin" / "python3",
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


def _load_internal_jobs(
    fetchers: dict[str, dict[str, Any]],
    overlay_path: Path,
) -> dict[str, dict[str, Any]]:
    jobs = {k: dict(v) for k, v in _DEFAULT_INTERNAL_JOBS.items()}
    if overlay_path.is_file():
        try:
            overlay = json.loads(overlay_path.read_text(encoding="utf-8"))
            for raw in overlay.get("jobs") or []:
                if not isinstance(raw, dict):
                    continue
                normalized = _normalize_internal_job_entry(raw)
                if not normalized:
                    continue
                key, entry = normalized
                if key in fetchers:
                    print(
                        f"[internal] skipping job {key}: collides with fetcher key",
                        file=sys.stderr,
                    )
                    continue
                jobs[key] = entry
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[internal] admin-jobs.json load failed: {exc!r}", file=sys.stderr)
    for key in list(jobs):
        if key in fetchers:
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
