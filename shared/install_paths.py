import json
import os
import sys
from pathlib import Path

_BUILT_MANIFEST_CACHE = None
_BUILT_MANIFEST_MTIME_NS = None
_FROZEN_DATA_ROOT = None
_FROZEN_MIGRATION_ATTEMPTED = False
PORTABLE_MARKER = "portable.txt"


def is_frozen():
    return bool(getattr(sys, "frozen", False))


def frozen_bundle_dir():
    return Path(sys.executable).resolve().parent


def frozen_server_exe():
    root = frozen_bundle_dir()
    for name in ("BAKLOG.exe", "BAKLOG"):
        candidate = root / name
        if candidate.is_file():
            return candidate
    return root / "BAKLOG.exe"


def frozen_tray_exe():
    root = frozen_bundle_dir()
    for name in ("BAKLOG Tray.exe", "BAKLOG Tray"):
        candidate = root / name
        if candidate.is_file():
            return candidate
    return root / "BAKLOG Tray.exe"


def legacy_frozen_data_dir():
    return frozen_bundle_dir()


def is_portable_frozen():
    if os.environ.get("BAKLOG_PORTABLE", "").strip().lower() in ("1", "true", "yes"):
        return True
    return (frozen_bundle_dir() / PORTABLE_MARKER).is_file()


def default_frozen_data_dir():
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA", "").strip()
        if base:
            return (Path(base) / "BAKLOG-Data").resolve()
        return (Path.home() / "AppData" / "Local" / "BAKLOG-Data").resolve()
    if sys.platform == "darwin":
        return (Path.home() / "Library" / "Application Support" / "BAKLOG").resolve()
    xdg = os.environ.get("XDG_DATA_HOME", "").strip()
    if xdg:
        return (Path(xdg).expanduser() / "baklog").resolve()
    return (Path.home() / ".local" / "share" / "baklog").resolve()


def resolved_data_dir_for_uninstall():
    override = os.environ.get("BAKLOG_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if is_portable_frozen():
        return legacy_frozen_data_dir()
    return default_frozen_data_dir()


def runtime_label():
    if not is_frozen():
        return "dev"
    if is_portable_frozen():
        return "portable"
    return "installed"


def _maybe_migrate_legacy_to(target):
    if is_portable_frozen():
        return
    legacy = legacy_frozen_data_dir()
    if legacy == target:
        return
    from shared.bundled_auth_env import sync_bundled_auth_env_to_data_dir
    from shared.data_dir_migration import migrate_legacy_colocated_data

    for note in migrate_legacy_colocated_data(legacy, target):
        print(f"[data_dir] {note}", file=sys.stderr, flush=True)
    if sync_bundled_auth_env_to_data_dir(legacy, target):
        print("[data_dir] synced bundled auth .env into data dir (upgrade path)", file=sys.stderr, flush=True)


def _resolve_frozen_data_root():
    if is_portable_frozen():
        return legacy_frozen_data_dir()
    target = default_frozen_data_dir()
    _maybe_migrate_legacy_to(target)
    return target


def bundle_root():
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parents[1]


def data_root():
    global _FROZEN_DATA_ROOT, _FROZEN_MIGRATION_ATTEMPTED
    override = os.environ.get("BAKLOG_DATA_DIR", "").strip()
    if override:
        target = Path(override).expanduser().resolve()
        if is_frozen() and (not _FROZEN_MIGRATION_ATTEMPTED):
            _FROZEN_MIGRATION_ATTEMPTED = True
            _maybe_migrate_legacy_to(target)
        return target
    if is_frozen():
        if _FROZEN_DATA_ROOT is not None:
            return _FROZEN_DATA_ROOT
        if not _FROZEN_MIGRATION_ATTEMPTED:
            _FROZEN_MIGRATION_ATTEMPTED = True
            _FROZEN_DATA_ROOT = _resolve_frozen_data_root()
        else:
            _FROZEN_DATA_ROOT = legacy_frozen_data_dir() if is_portable_frozen() else default_frozen_data_dir()
        return _FROZEN_DATA_ROOT
    return bundle_root()


def built_manifest_path():
    return bundle_root() / "dist" / "manifest.json"


def _env_serve_built():
    return os.environ.get("BAKLOG_SERVE_BUILT", "").strip().lower() in ("1", "true", "yes")


def serve_built_frontend():
    if not built_manifest_path().is_file():
        return False
    return is_frozen() or _env_serve_built()


def load_built_manifest():
    global _BUILT_MANIFEST_CACHE, _BUILT_MANIFEST_MTIME_NS
    if not serve_built_frontend():
        return {}
    path = built_manifest_path()
    try:
        mtime_ns = path.stat().st_mtime_ns
    except OSError:
        return {}
    if _BUILT_MANIFEST_CACHE is not None and _BUILT_MANIFEST_MTIME_NS == mtime_ns:
        return _BUILT_MANIFEST_CACHE
    try:
        _BUILT_MANIFEST_CACHE = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _BUILT_MANIFEST_CACHE = {}
    _BUILT_MANIFEST_MTIME_NS = mtime_ns
    return _BUILT_MANIFEST_CACHE


def built_immutable_assets():
    manifest = load_built_manifest()
    if not manifest:
        return frozenset()
    out = set()
    for key, val in manifest.items():
        if key in ("builtAt", "version"):
            continue
        if key == "js/chunks" and isinstance(val, list):
            out.update((str(v) for v in val))
        elif isinstance(val, str) and val:
            out.add(val.replace("\\", "/"))
    return frozenset(out)


def static_root():
    return bundle_root()
