"""Pro cloud mirror — upload scheduling, Supabase Storage, and local state."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

from shared.entitlement import is_pro_background
from shared.mirror_session import get_mirror_session
from shared.pro_settings import read_pro_settings
from shared.profile_paths import get_active_profile_id, profile_root, runs_dir

DEBOUNCE_SEC = 30.0
_FLUSH_POLL_SEC = 5.0

_lock = threading.Lock()
_pending: dict[str, dict[str, Any]] = {}
_worker_started = False


def start_flush_worker() -> None:
    """Start the debounced mirror flush thread (idempotent)."""
    global _worker_started
    with _lock:
        if _worker_started:
            return
        _worker_started = True
    thread = threading.Thread(
        target=_flush_loop,
        name="cloud-mirror-flush",
        daemon=True,
    )
    thread.start()


def _flush_loop() -> None:
    while True:
        time.sleep(_FLUSH_POLL_SEC)
        try:
            maybe_flush_mirror_uploads()
        except Exception as exc:  # noqa: BLE001
            if os.environ.get("BAKLOG_DEBUG"):
                print(f"[cloud_mirror] flush loop error: {exc!r}", file=sys.stderr)


def mirrorable_relative_path(path: Path, *, profile_id: str | None = None) -> str | None:
    """Return profile-relative artifact path if mirrorable, else None."""
    pid = profile_id if profile_id is not None else get_active_profile_id()
    root = profile_root(profile_id=pid).resolve()
    try:
        resolved = path.resolve()
        rel = resolved.relative_to(root)
    except (ValueError, OSError):
        return None
    rel_posix = rel.as_posix()
    if _is_denied_relative(rel_posix):
        return None
    if _is_allowed_relative(rel_posix):
        return rel_posix
    return None


def _is_denied_relative(rel_posix: str) -> bool:
    lower = rel_posix.lower()
    if lower.startswith("cache/") or "/cache/" in lower:
        return True
    if lower.startswith("auth/") or "/auth/" in lower:
        return True
    if lower.endswith("secrets.bin") or lower.endswith(".env"):
        return True
    if lower.endswith("pro_settings.json"):
        return True
    return False


def _is_allowed_relative(rel_posix: str) -> bool:
    name = Path(rel_posix).name
    if rel_posix == "data/personal.json":
        return True
    if name in ("itad_prices.json", "free_claims.json"):
        return True
    if name.startswith("games_wishlist_") and name.endswith(".json"):
        return True
    if name.startswith("games_") and name.endswith(".json"):
        return True
    return False


def mirror_upload_allowed(*, profile_id: str | None = None) -> bool:
    """True when Pro + opt-in toggle allow mirror upload."""
    if not is_pro_background():
        return False
    settings = read_pro_settings(profile_id=profile_id)
    if not settings.get("cloudMirrorEnabled"):
        return False
    return True


def mirror_read_allowed(*, authorization: str | None) -> bool:
    """Pro users may read their cloud mirror via bearer-authenticated API."""
    from shared.entitlement import is_pro
    from shared.supabase_auth import auth_enabled

    if not auth_enabled():
        return False
    return is_pro(authorization)


def schedule_mirror_upload(path: Path, *, profile_id: str | None = None) -> None:
    """Queue a mirror artifact after a successful local write (debounced)."""
    pid = profile_id if profile_id is not None else get_active_profile_id()
    rel = mirrorable_relative_path(path, profile_id=pid)
    if rel is None:
        return
    now = time.time()
    with _lock:
        entry = _pending.setdefault(pid, {"paths": set(), "flush_at": now + DEBOUNCE_SEC})
        paths = entry["paths"]
        if not isinstance(paths, set):
            paths = set(paths)
            entry["paths"] = paths
        paths.add(rel)
        entry["flush_at"] = now + DEBOUNCE_SEC


def maybe_flush_mirror_uploads(*, force: bool = False) -> None:
    """Upload pending artifacts whose debounce window elapsed."""
    now = time.time()
    due: list[tuple[str, set[str]]] = []
    with _lock:
        for pid, entry in list(_pending.items()):
            flush_at = float(entry.get("flush_at") or 0)
            paths = entry.get("paths") or set()
            if not paths:
                _pending.pop(pid, None)
                continue
            if force or now >= flush_at:
                due.append((pid, set(paths)))
                _pending.pop(pid, None)
    for pid, paths in due:
        _flush_profile_uploads(pid, paths)


def _mirror_state_path(profile_id: str) -> Path:
    return runs_dir(profile_id=profile_id) / "mirror_upload_state.json"


def read_mirror_upload_state(*, profile_id: str | None = None) -> dict[str, Any]:
    pid = profile_id if profile_id is not None else get_active_profile_id()
    try:
        doc = json.loads(_mirror_state_path(pid).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"artifacts": {}, "last_upload_at": None}
    if not isinstance(doc, dict):
        return {"artifacts": {}, "last_upload_at": None}
    artifacts = doc.get("artifacts")
    if not isinstance(artifacts, dict):
        artifacts = {}
    return {
        "artifacts": artifacts,
        "last_upload_at": doc.get("last_upload_at"),
    }


def _save_mirror_upload_state(profile_id: str, uploaded: dict[str, str]) -> None:
    if not uploaded:
        return
    path = _mirror_state_path(profile_id)
    state = read_mirror_upload_state(profile_id=profile_id)
    artifacts = dict(state.get("artifacts") or {})
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for rel, status in uploaded.items():
        artifacts[rel] = {"status": status, "uploaded_at": now}
    doc = {"artifacts": artifacts, "last_upload_at": now}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def _flush_profile_uploads(profile_id: str, paths: set[str]) -> None:
    if not mirror_upload_allowed(profile_id=profile_id):
        return
    from shared.supabase_auth import auth_enabled

    if not auth_enabled():
        return
    session = get_mirror_session()
    if session is None:
        if os.environ.get("BAKLOG_DEBUG"):
            print("[cloud_mirror] skip upload: no cached bearer session", file=sys.stderr)
        return
    user_id, bearer = session
    from shared.supabase_mirror import upload_mirror_object, upsert_mirror_snapshot_row

    root = profile_root(profile_id=profile_id)
    uploaded: dict[str, str] = {}
    errors: list[str] = []
    for rel in sorted(paths):
        file_path = root / rel
        try:
            body = file_path.read_bytes()
        except OSError as exc:
            errors.append(f"{rel}: read failed ({exc})")
            continue
        try:
            upload_mirror_object(
                user_id=user_id,
                profile_id=profile_id,
                artifact_path=rel,
                body=body,
                bearer_token=bearer,
            )
            upsert_mirror_snapshot_row(
                user_id=user_id,
                profile_id=profile_id,
                artifact_path=rel,
                byte_size=len(body),
                bearer_token=bearer,
            )
            uploaded[rel] = "ok"
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{rel}: {exc}")
            uploaded[rel] = "error"
    _save_mirror_upload_state(profile_id, uploaded)
    if os.environ.get("BAKLOG_DEBUG"):
        payload = {
            "profile_id": profile_id,
            "uploaded": sorted(uploaded.keys()),
            "errors": errors,
        }
        print(f"[cloud_mirror] upload flush: {json.dumps(payload)}", file=sys.stderr, flush=True)


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def list_remote_mirror_artifacts(
    *,
    authorization: str,
    profile_id: str | None = None,
) -> list[dict[str, Any]]:
    """List mirror objects in Supabase Storage for the signed-in user."""
    from shared.supabase_auth import verify_bearer_user
    from shared.supabase_mirror import list_mirror_objects

    user = verify_bearer_user(authorization)
    if not user:
        raise PermissionError("invalid session")
    user_id = str(user.get("id") or "")
    pid = profile_id if profile_id is not None else get_active_profile_id()
    token = _bearer_token(authorization)
    rows = list_mirror_objects(user_id=user_id, profile_id=pid, bearer_token=token)
    out: list[dict[str, Any]] = []
    for row in rows:
        name = str(row.get("name") or "").strip().lstrip("/")
        if not name or name.endswith("/"):
            continue
        out.append(
            {
                "path": name,
                "id": row.get("id"),
                "updated_at": row.get("updated_at"),
                "metadata": row.get("metadata"),
            }
        )
    out.sort(key=lambda item: item.get("path") or "")
    return out


def download_remote_mirror_artifact(
    *,
    authorization: str,
    artifact_path: str,
    profile_id: str | None = None,
) -> bytes:
    from shared.supabase_auth import verify_bearer_user
    from shared.supabase_mirror import download_mirror_object

    rel = mirrorable_relative_path(
        profile_root(profile_id=profile_id or get_active_profile_id()) / artifact_path,
        profile_id=profile_id,
    )
    if rel is None:
        raise ValueError("artifact not allowed")
    user = verify_bearer_user(authorization)
    if not user:
        raise PermissionError("invalid session")
    user_id = str(user.get("id") or "")
    pid = profile_id if profile_id is not None else get_active_profile_id()
    token = _bearer_token(authorization)
    return download_mirror_object(
        user_id=user_id,
        profile_id=pid,
        artifact_path=rel,
        bearer_token=token,
    )


def _bearer_token(authorization: str) -> str:
    parts = authorization.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise PermissionError("missing bearer token")
    token = parts[1].strip()
    if not token:
        raise PermissionError("missing bearer token")
    return token
