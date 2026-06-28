import json
import sys
import tempfile
from pathlib import Path

from shared.install_paths import data_root, frozen_bundle_dir, is_frozen, is_portable_frozen

_COMMUNITY_JSON = Path(__file__).resolve().parent / "community.json"
_DEFAULT_RELEASES_API = "https://api.github.com/repos/Ogrods/BAKLOG/releases/latest"
_TEMP_DIR_MARKERS = ("\\temp\\", "/temp/", "\\tmp\\", "/tmp/", "rar$", "7z", "inetcache")


def is_running_from_temp_dir(path):
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


def run_boot_checks(data_root):
    check_data_location()
    if not is_frozen() or sys.platform != "win32":
        return
    try:
        from shared.startup import reconcile_startup

        if reconcile_startup():
            print("NOTE: Removed stale BAKLOG login autostart (target executable missing).", flush=True)
    except Exception as exc:
        print(f"[startup] reconcile skipped: {exc!r}", file=sys.stderr, flush=True)


def check_data_location():
    if not is_frozen():
        return
    app_dir = frozen_bundle_dir()
    if not is_running_from_temp_dir(app_dir):
        return
    if is_portable_frozen():
        print(
            "WARNING: BAKLOG is running from a temporary folder (e.g. inside a zip preview).\nPortable mode stores library data beside the exe, so it may be lost when Windows cleans up. Unzip to Desktop or Documents, or remove portable.txt to use the default data folder.",
            file=sys.stderr,
            flush=True,
        )
        return
    data_hint = data_root()
    print(
        f"WARNING: BAKLOG is running from a temporary folder (e.g. inside a zip preview).\nLibrary data is stored separately at:\n  {data_hint}\nUnzip or install BAKLOG to a permanent folder (Desktop, Documents) before connecting stores.",
        file=sys.stderr,
        flush=True,
    )


def redact_user_path(path):
    try:
        resolved = path.resolve()
        home = Path.home().resolve()
        if resolved == home or home in resolved.parents:
            rel = resolved.relative_to(home)
            return "~/" + rel.as_posix()
    except (OSError, RuntimeError, ValueError):
        pass
    return str(path)


def normalize_version_tag(tag):
    return tag.lstrip("vV").strip()


def version_tuple(version):
    parts = []
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


def update_available(current, latest):
    return version_tuple(latest) > version_tuple(current)


def github_releases_latest_api_url():
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


def fetch_latest_github_release():
    import urllib.error
    import urllib.request

    url = github_releases_latest_api_url()
    req = urllib.request.Request(
        url, headers={"Accept": "application/vnd.github+json", "User-Agent": "BAKLOG-local-update-check"}
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {}
        raise
    return raw if isinstance(raw, dict) else {}


def tail_text_file(path, *, max_lines=80):
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return lines[-max_lines:]


def _apply_script_present():
    from shared.update_platform import apply_script_name

    return (frozen_bundle_dir() / apply_script_name()).is_file()


def _apply_supported_for_runtime():
    from shared.install_paths import runtime_label
    from shared.update_platform import is_in_app_apply_platform

    if runtime_label() not in {"installed", "portable"}:
        return False
    if not is_frozen() or not is_in_app_apply_platform():
        return False
    return _apply_script_present()


def build_update_check_payload(current_version, *, fetchers_in_flight=False, sign_in_active=False):
    from shared.install_paths import runtime_label
    from shared.install_visibility import install_visibility_fields
    from shared.update_messages import resolve_apply_blocked_for_check
    from shared.update_platform import is_in_app_apply_platform
    from shared.update_release import UpdateSecurityError, build_release_artifacts, recommended_artifact
    from shared.update_snooze import is_version_dismissed

    root = data_root()
    runtime = runtime_label()
    apply_ok = _apply_supported_for_runtime()
    base = {
        "current": current_version,
        "latest": None,
        "update_available": False,
        "url": None,
        "runtime_label": runtime,
        "recommended_artifact": recommended_artifact(runtime),
        "download_url": None,
        "sha256": None,
        "apply_supported": apply_ok,
        "apply_blocked_reason": None,
        "apply_blocked_message": None,
        "dismissed": False,
        "release_notes": None,
        "published_at": None,
        "fetchers_in_flight": fetchers_in_flight,
        "sign_in_active": sign_in_active,
        **install_visibility_fields(current_version),
    }
    try:
        release = fetch_latest_github_release()
        artifacts = build_release_artifacts(release)
        latest = artifacts.version
        url = artifacts.html_url or None
        update = bool(latest) and update_available(current_version, latest)
        zip_url = artifacts.zip_url if update else None
        sha256 = artifacts.sha256 if update else None
        apply_supported, blocked_reason, blocked_message = resolve_apply_blocked_for_check(
            update_available=update,
            zip_url=zip_url,
            sha256=sha256,
            runtime_label=runtime,
            frozen=is_frozen(),
            in_apply_platform=is_in_app_apply_platform(),
            running_from_temp=is_frozen() and is_running_from_temp_dir(frozen_bundle_dir()),
            apply_script_present=_apply_script_present(),
        )
        can_download = bool(update and zip_url and (sha256 or apply_ok))
        base.update(
            {
                "latest": latest or None,
                "update_available": update,
                "url": url,
                "download_url": zip_url if can_download else None,
                "sha256": sha256 or None if can_download else None,
                "sha256_url": artifacts.sha256_url if can_download else None,
                "release_notes": artifacts.release_notes if update else None,
                "published_at": artifacts.published_at if update else None,
                "apply_supported": apply_supported,
                "apply_blocked_reason": blocked_reason,
                "apply_blocked_message": blocked_message,
                "dismissed": is_version_dismissed(root, latest) if update else False,
            }
        )
        return base
    except UpdateSecurityError as exc:
        base["error"] = str(exc)
        return base
    except Exception as exc:
        base["error"] = str(exc)
        return base


def build_diagnostics_payload(*, data_root, version, load_run_history):
    from shared.install_paths import runtime_label
    from shared.install_visibility import install_visibility_fields
    from shared.update_release import recommended_artifact

    history = load_run_history()[-10:]
    recent_runs = []
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
    update_status = None
    try:
        from shared.update_manager import get_update_manager

        def _noop_in_flight():
            return False

        update_status = get_update_manager(
            current_version=lambda: version, has_in_flight_runs=_noop_in_flight
        ).status_dict()
    except Exception:
        update_status = None
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
        "apply_supported": _apply_supported_for_runtime(),
        "recommended_artifact": recommended_artifact(runtime_label()),
        "update": update_status,
        **install_visibility_fields(version),
    }
