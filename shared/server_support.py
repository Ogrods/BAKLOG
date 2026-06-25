"""Boot checks and opt-in support endpoints helpers (keeps server.py lean)."""

from __future__ import annotations

import json
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from shared.install_paths import data_root, frozen_bundle_dir, is_frozen, is_portable_frozen

_COMMUNITY_JSON = Path(__file__).resolve().parent / "community.json"
_DEFAULT_RELEASES_API = "https://api.github.com/repos/Ogrods/BAKLOG/releases/latest"

_TEMP_DIR_MARKERS = (
    "\\temp\\",
    "/temp/",
    "\\tmp\\",
    "/tmp/",
    "rar$",
    "7z",
    "inetcache",
)


def is_running_from_temp_dir(path: Path) -> bool:
    """True when a frozen build runs from a purgeable temp/zip-extract folder."""
    if not is_frozen():
        return False
    try:
        resolved = path.resolve()
        temp_root = Path(tempfile.gettempdir()).resolve()
        if resolved == temp_root or temp_root in resolved.parents:
            return True
        lower = str(resolved).lower()
        return any(marker in lower for marker in _TEMP_DIR_MARKERS)
    except OSError:
        return False


def run_boot_checks(data_root: Path) -> None:
    """Non-fatal boot warnings and Windows autostart self-heal."""
    check_data_location()
    if not is_frozen() or sys.platform != "win32":
        return
    try:
        from shared.startup import reconcile_startup

        if reconcile_startup():
            print(
                "NOTE: Removed stale BAKLOG login autostart (target executable missing).",
                flush=True,
            )
    except Exception as exc:  # noqa: BLE001 - must not block server boot
        print(f"[startup] reconcile skipped: {exc!r}", file=sys.stderr, flush=True)


def check_data_location() -> None:
    """Warn when the frozen app bundle runs from a purgeable temp/zip-extract folder."""
    if not is_frozen():
        return
    app_dir = frozen_bundle_dir()
    if not is_running_from_temp_dir(app_dir):
        return
    if is_portable_frozen():
        print(
            "WARNING: BAKLOG is running from a temporary folder (e.g. inside a zip preview).\n"
            "Portable mode stores library data beside the exe, so it may be lost when "
            "Windows cleans up. Unzip to Desktop or Documents, or remove portable.txt "
            "to use the default data folder.",
            file=sys.stderr,
            flush=True,
        )
        return
    data_hint = data_root()
    print(
        "WARNING: BAKLOG is running from a temporary folder (e.g. inside a zip preview).\n"
        f"Library data is stored separately at:\n  {data_hint}\n"
        "Unzip or install BAKLOG to a permanent folder (Desktop, Documents) "
        "before connecting stores.",
        file=sys.stderr,
        flush=True,
    )


def redact_user_path(path: Path) -> str:
    """Support-safe path string with home prefix replaced by ~."""
    try:
        resolved = path.resolve()
        home = Path.home().resolve()
        if resolved == home or home in resolved.parents:
            rel = resolved.relative_to(home)
            return "~/" + rel.as_posix()
    except (OSError, RuntimeError, ValueError):
        pass
    return str(path)


def normalize_version_tag(tag: str) -> str:
    return tag.lstrip("vV").strip()


def version_tuple(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for piece in version.split("."):
        digits = ""
        for ch in piece:
            if ch.isdigit():
                digits += ch
            else:
                break
        if digits:
            parts.append(int(digits))
    return tuple(parts) if parts else (0,)


def update_available(current: str, latest: str) -> bool:
    return version_tuple(latest) > version_tuple(current)


def github_releases_latest_api_url() -> str:
    """Latest-release API URL derived from shared/community.json github_repo."""
    try:
        raw = json.loads(_COMMUNITY_JSON.read_text(encoding="utf-8"))
        repo = str(raw.get("github_repo", "")).strip().rstrip("/")
        if repo.startswith("https://github.com/"):
            slug = repo[len("https://github.com/") :]
            if slug:
                return f"https://api.github.com/repos/{slug}/releases/latest"
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return _DEFAULT_RELEASES_API


def fetch_latest_github_release() -> dict[str, Any]:
    import urllib.error
    import urllib.request

    url = github_releases_latest_api_url()
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "BAKLOG-local-update-check",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {}
        raise
    return raw if isinstance(raw, dict) else {}


def tail_text_file(path: Path, *, max_lines: int = 80) -> list[str]:
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return lines[-max_lines:]


def build_update_check_payload(current_version: str) -> dict[str, Any]:
    try:
        release = fetch_latest_github_release()
        latest = normalize_version_tag(str(release.get("tag_name", "")))
        url = str(release.get("html_url", "") or "")
        return {
            "current": current_version,
            "latest": latest or None,
            "update_available": bool(latest) and update_available(current_version, latest),
            "url": url or None,
        }
    except Exception as exc:  # noqa: BLE001 - soft failure for opt-in check
        return {
            "current": current_version,
            "latest": None,
            "update_available": False,
            "url": None,
            "error": str(exc),
        }


def build_diagnostics_payload(
    *,
    data_root: Path,
    version: str,
    load_run_history: Callable[[], list[dict[str, Any]]],
) -> dict[str, Any]:
    history = load_run_history()[-10:]
    recent_runs: list[dict[str, Any]] = []
    for entry in history:
        if not isinstance(entry, dict):
            continue
        recent_runs.append(
            {
                "id": entry.get("id"),
                "key": entry.get("key"),
                "label": entry.get("label"),
                "status": entry.get("status"),
                "exit_code": entry.get("exit_code"),
                "started_at": entry.get("started_at"),
                "ended_at": entry.get("ended_at"),
            }
        )
    return {
        "version": version,
        "platform": sys.platform,
        "frozen": is_frozen(),
        "data_dir": data_root.name,
        "data_dir_path": redact_user_path(data_root),
        "portable": is_frozen() and is_portable_frozen(),
        "running_from_temp": is_frozen() and is_running_from_temp_dir(frozen_bundle_dir()),
        "recent_runs": recent_runs,
        "refresh_log_tail": tail_text_file(data_root / "refresh.log"),
    }
