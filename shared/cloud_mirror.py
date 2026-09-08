"""Opt-in Pro cloud mirror: schedule uploads, list/download, import into active profile."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from shared.entitlement import is_pro_background
from shared.mirror_artifacts import (
    is_allowed_relative,
    is_denied_relative,
)
from shared.mirror_artifacts import (
    mirrorable_relative_path as _artifact_rel,
)
from shared.mirror_session import get_mirror_session
from shared.pro_settings import read_pro_settings
from shared.profile_paths import get_active_profile_id, profile_root, runs_dir
from shared.supabase_mirror import mirror_device_id

DEBOUNCE_SEC = 30.0
_FLUSH_POLL_SEC = 5.0
MIRROR_MAX_UPLOAD_BYTES = 25 * 1024 * 1024
_lock = threading.Lock()
_pending: dict[str, dict[str, Any]] = {}
_worker_started = False


class MirrorProfileMismatch(ValueError):
    """Import requested a profile other than the active one."""


def start_flush_worker() -> None:
    global _worker_started
    with _lock:
        if _worker_started:
            return
        _worker_started = True
    thread = threading.Thread(target=_flush_loop, name="cloud-mirror-flush", daemon=True)
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
    pid = profile_id if profile_id is not None else get_active_profile_id()
    root = profile_root(profile_id=pid)
    return _artifact_rel(path, profile_root=root)


def mirror_upload_allowed(*, profile_id: str | None = None) -> bool:
    from shared.pro_capabilities import capability_registry_status

    # Capability soon/off must block uploads even if a client forced opt-in on disk.
    if capability_registry_status("cloud_sync_mirror") != "live":
        return False
    if not is_pro_background():
        return False
    settings = read_pro_settings(profile_id=profile_id)
    return bool(settings.get("cloudMirrorEnabled"))


def mirror_read_allowed(*, authorization: str | None) -> bool:
    from shared.entitlement import is_pro
    from shared.supabase_auth import auth_enabled

    if not auth_enabled():
        return False
    return is_pro(authorization)


def schedule_mirror_upload(path: Path, *, profile_id: str | None = None) -> None:
    pid = profile_id if profile_id is not None else get_active_profile_id()
    rel = mirrorable_relative_path(path, profile_id=pid)
    if rel is None:
        return
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    if size > MIRROR_MAX_UPLOAD_BYTES:
        _save_mirror_upload_state(pid, {rel: "too_large"})
        if os.environ.get("BAKLOG_DEBUG"):
            print(
                f"[cloud_mirror] skip {rel}: {size} bytes exceeds {MIRROR_MAX_UPLOAD_BYTES}",
                file=sys.stderr,
            )
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
    """Resolve mirror upload state under a validated profile runs dir."""
    from shared.profile_paths import normalize_profile_id

    pid = normalize_profile_id(profile_id)
    runs = runs_dir(profile_id=pid).resolve()
    path = (runs / "mirror_upload_state.json").resolve()
    if not path.is_relative_to(runs):
        raise ValueError("mirror state path escapes profile runs dir")
    return path


def read_mirror_upload_state(*, profile_id: str | None = None) -> dict[str, Any]:
    raw_pid = profile_id if profile_id is not None else get_active_profile_id()
    try:
        from shared.profile_paths import normalize_profile_id

        pid = normalize_profile_id(raw_pid)
    except ValueError:
        return {"artifacts": {}, "last_upload_at": None, "device_id": None}
    try:
        doc = json.loads(_mirror_state_path(pid).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {"artifacts": {}, "last_upload_at": None, "device_id": None}
    if not isinstance(doc, dict):
        return {"artifacts": {}, "last_upload_at": None, "device_id": None}
    artifacts = doc.get("artifacts")
    if not isinstance(artifacts, dict):
        artifacts = {}
    return {
        "artifacts": artifacts,
        "last_upload_at": doc.get("last_upload_at"),
        "device_id": doc.get("device_id"),
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
    doc = {
        "artifacts": artifacts,
        "last_upload_at": now,
        "device_id": mirror_device_id(),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def _looks_like_account_profile_id(profile_id: str) -> bool:
    try:
        uuid.UUID(str(profile_id))
        return True
    except ValueError:
        return False


def _flush_profile_uploads(profile_id: str, paths: set[str]) -> None:
    from shared.profile_paths import normalize_profile_id

    try:
        pid = normalize_profile_id(profile_id)
    except ValueError:
        return
    if not mirror_upload_allowed(profile_id=pid):
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
    # Account profiles are keyed by Supabase user id — never upload under another account.
    if _looks_like_account_profile_id(pid) and pid != user_id:
        if os.environ.get("BAKLOG_DEBUG"):
            print(
                f"[cloud_mirror] skip upload: profile {pid!r} != session user {user_id!r}",
                file=sys.stderr,
            )
        return
    from shared.supabase_mirror import upload_mirror_object, upsert_mirror_snapshot_row

    root = profile_root(profile_id=pid).resolve()
    uploaded: dict[str, str] = {}
    errors: list[str] = []
    device = mirror_device_id()
    for rel in sorted(paths):
        if not is_allowed_relative(rel) or is_denied_relative(rel):
            continue
        file_path = (root / rel).resolve()
        if not file_path.is_relative_to(root):
            continue
        try:
            body = file_path.read_bytes()
        except OSError as exc:
            errors.append(f"{rel}: read failed ({exc})")
            continue
        if len(body) > MIRROR_MAX_UPLOAD_BYTES:
            uploaded[rel] = "too_large"
            continue
        try:
            upload_mirror_object(
                user_id=user_id, profile_id=pid, artifact_path=rel, body=body, bearer_token=bearer
            )
            upsert_mirror_snapshot_row(
                user_id=user_id,
                profile_id=pid,
                artifact_path=rel,
                byte_size=len(body),
                bearer_token=bearer,
                device_id=device,
            )
            uploaded[rel] = "ok"
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{rel}: {exc}")
            uploaded[rel] = "error"
    _save_mirror_upload_state(pid, uploaded)
    if os.environ.get("BAKLOG_DEBUG"):
        payload = {"profile_id": pid, "uploaded": sorted(uploaded.keys()), "errors": errors}
        print(f"[cloud_mirror] upload flush: {json.dumps(payload)}", file=sys.stderr, flush=True)


def list_remote_mirror_artifacts(*, authorization: str, profile_id: str | None = None) -> list[dict[str, Any]]:
    from shared.supabase_auth import verify_bearer_user
    from shared.supabase_mirror import list_mirror_artifacts

    user = verify_bearer_user(authorization)
    if not user:
        raise PermissionError("invalid session")
    user_id = str(user.get("id") or "")
    if profile_id is not None:
        from shared.profile_paths import normalize_profile_id

        pid = normalize_profile_id(profile_id)
    else:
        pid = get_active_profile_id()
    token = _bearer_token(authorization)
    rows = list_mirror_artifacts(user_id=user_id, profile_id=pid, bearer_token=token)
    out: list[dict[str, Any]] = []
    for row in rows:
        name = str(row.get("name") or "").strip().lstrip("/")
        if not name or name.endswith("/"):
            continue
        if not is_allowed_relative(name):
            continue
        out.append(
            {"path": name, "id": row.get("id"), "updated_at": row.get("updated_at"), "metadata": row.get("metadata")}
        )
    out.sort(key=lambda item: item.get("path") or "")
    return out


def download_remote_mirror_artifact(
    *, authorization: str, artifact_path: str, profile_id: str | None = None
) -> bytes:
    from shared.supabase_auth import verify_bearer_user
    from shared.supabase_mirror import download_mirror_object

    pid = profile_id if profile_id is not None else get_active_profile_id()
    if profile_id is not None:
        from shared.profile_paths import normalize_profile_id

        pid = normalize_profile_id(profile_id)
    rel = str(artifact_path or "").strip().lstrip("/")
    if not is_allowed_relative(rel):
        raise ValueError("artifact not allowed")
    user = verify_bearer_user(authorization)
    if not user:
        raise PermissionError("invalid session")
    user_id = str(user.get("id") or "")
    token = _bearer_token(authorization)
    return download_mirror_object(user_id=user_id, profile_id=pid, artifact_path=rel, bearer_token=token)


def _bearer_token(authorization: str) -> str:
    parts = authorization.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise PermissionError("missing bearer token")
    token = parts[1].strip()
    if not token:
        raise PermissionError("missing bearer token")
    return token


def _parse_mirror_json(body: bytes, artifact_path: str) -> Any:
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{artifact_path}: invalid JSON") from exc


def _validate_mirror_staged_doc(rel: str, doc: Any, *, allow_empty_catalogs: bool) -> None:
    from shared.server_catalog_import import is_allowed_catalog_filename, validate_catalog_doc

    if rel == "data/personal.json":
        if not isinstance(doc, dict):
            raise ValueError(f"{rel}: must be a JSON object")
        return
    if is_allowed_catalog_filename(rel):
        validate_catalog_doc(rel, doc)
        if allow_empty_catalogs or rel == "itad_prices.json":
            return
        if rel.startswith("games_"):
            games = doc.get("games")
            if isinstance(games, list) and len(games) == 0:
                raise ValueError(f"{rel}: empty games list refused")
        return
    raise ValueError(f"unsupported mirror artifact: {rel}")


def _mirror_artifact_write_path(rel: str, *, profile_id: str) -> Path:
    from shared.profile_paths import catalog_path, personal_path

    if not is_allowed_relative(rel):
        raise ValueError(f"unsupported mirror artifact: {rel}")
    if rel == "data/personal.json":
        path = personal_path(profile_id=profile_id)
    else:
        from shared.server_catalog_import import is_allowed_catalog_filename

        if not is_allowed_catalog_filename(rel):
            raise ValueError(f"unsupported mirror artifact: {rel}")
        path = catalog_path(rel, profile_id=profile_id)
    root = profile_root(profile_id=profile_id).resolve()
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"path escapes profile root: {rel}")
    return path


def import_remote_mirror_to_profile(
    *,
    authorization: str,
    profile_id: str | None = None,
    paths: list[str] | None = None,
    include_personal: bool = True,
    allow_empty_catalogs: bool = False,
) -> dict[str, Any]:
    """Import mirrored artifacts into the **active** profile only.

    Naming a different ``profile_id`` raises :class:`MirrorProfileMismatch` (HTTP 409).
    """
    from shared.server_catalog_import import import_catalog_payload, is_allowed_catalog_filename
    from shared.server_personal import save_personal_doc

    active = get_active_profile_id()
    if profile_id is not None and str(profile_id) != active:
        raise MirrorProfileMismatch(
            f"profile mismatch (active={active!r}, claimed={str(profile_id)!r})"
        )
    pid = active
    remote_rows = list_remote_mirror_artifacts(authorization=authorization, profile_id=pid)
    remote_paths = {str(row.get("path") or "").strip() for row in remote_rows}
    remote_paths.discard("")
    candidates: list[str] = []
    for path in sorted(remote_paths):
        if not is_allowed_relative(path):
            continue
        if path == "data/personal.json" and not include_personal:
            continue
        candidates.append(path)
    if paths is not None:
        wanted = {str(item).strip().lstrip("/") for item in paths if str(item).strip()}
        candidates = [rel for rel in candidates if rel in wanted]
    if not candidates:
        raise ValueError("no importable mirror artifacts")
    staged: dict[str, Any] = {}
    for rel in candidates:
        body = download_remote_mirror_artifact(authorization=authorization, artifact_path=rel, profile_id=pid)
        doc = _parse_mirror_json(body, rel)
        _validate_mirror_staged_doc(rel, doc, allow_empty_catalogs=allow_empty_catalogs)
        staged[rel] = doc
    write_paths = [_mirror_artifact_write_path(rel, profile_id=pid) for rel in staged]
    backups: dict[Path, bytes | None] = {}
    for path in write_paths:
        try:
            backups[path] = path.read_bytes() if path.is_file() else None
        except OSError:
            backups[path] = None
    imported: list[str] = []
    personal_saved = False
    try:
        catalogs: dict[str, Any] = {}
        for rel, doc in staged.items():
            if rel == "data/personal.json":
                # save_personal_doc always writes the active profile (no profile_id arg).
                save_personal_doc(doc, allow_empty=False)
                imported.append(rel)
                personal_saved = True
                continue
            if is_allowed_catalog_filename(rel):
                catalogs[rel] = doc
        if catalogs:
            batch = import_catalog_payload({"catalogs": catalogs, "profile": pid})
            imported.extend(batch.get("imported") or [])
    except Exception:
        for path, prior in backups.items():
            try:
                if prior is None:
                    if path.is_file():
                        path.unlink()
                else:
                    path.write_bytes(prior)
            except OSError:
                pass
        raise
    seen: set[str] = set()
    ordered: list[str] = []
    for name in imported:
        if name in seen:
            continue
        seen.add(name)
        ordered.append(name)
    return {"ok": True, "imported": ordered, "count": len(ordered), "personal": personal_saved}
