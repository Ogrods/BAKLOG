"""Supabase Storage + snapshots table helpers for the Pro cloud mirror."""

from __future__ import annotations

import json
import platform
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

MIRROR_BUCKET = "baklog-mirror"
_STORAGE_TIMEOUT_SEC = 120


def _base_url() -> str:
    from shared.supabase_auth import _supabase_url

    url = _supabase_url()
    if not url:
        raise RuntimeError("Supabase URL not configured")
    return url.rstrip("/")


def _anon_key() -> str:
    from shared.supabase_auth import _anon_key

    key = _anon_key()
    if not key:
        raise RuntimeError("Supabase anon key not configured")
    return key


def mirror_device_id() -> str:
    host = socket.gethostname() or "host"
    system = platform.system() or "os"
    return f"{system}:{host}"[:120]


def mirror_object_key(user_id: str, profile_id: str, artifact_path: str) -> str:
    uid = (user_id or "").strip().strip("/")
    pid = (profile_id or "").strip().strip("/")
    rel = (artifact_path or "").strip().lstrip("/")
    if not uid or not pid or not rel:
        raise ValueError("invalid mirror object key parts")
    if ".." in rel.split("/"):
        raise ValueError("invalid artifact path")
    return f"{uid}/{pid}/{rel}"


def upload_mirror_object(
    *,
    user_id: str,
    profile_id: str,
    artifact_path: str,
    body: bytes,
    bearer_token: str,
    content_type: str = "application/json",
) -> Any:
    key = mirror_object_key(user_id, profile_id, artifact_path)
    encoded = "/".join(urllib.parse.quote(part, safe="") for part in key.split("/"))
    url = f"{_base_url()}/storage/v1/object/{MIRROR_BUCKET}/{encoded}"
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "apikey": _anon_key(),
            "Authorization": f"Bearer {bearer_token}",
            "Content-Type": content_type,
            "x-upsert": "true",
        },
    )
    return _json_request(req)


def download_mirror_object(*, user_id: str, profile_id: str, artifact_path: str, bearer_token: str) -> bytes:
    key = mirror_object_key(user_id, profile_id, artifact_path)
    encoded = "/".join(urllib.parse.quote(part, safe="") for part in key.split("/"))
    url = f"{_base_url()}/storage/v1/object/{MIRROR_BUCKET}/{encoded}"
    req = urllib.request.Request(
        url, method="GET", headers={"apikey": _anon_key(), "Authorization": f"Bearer {bearer_token}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=_STORAGE_TIMEOUT_SEC) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GET mirror object HTTP {exc.code}: {detail}") from exc


def _list_prefix(*, prefix: str, bearer_token: str, limit: int = 200) -> list[dict[str, Any]]:
    """List Storage objects under ``prefix``, paginating until a short page (SEC-007)."""
    url = f"{_base_url()}/storage/v1/object/list/{MIRROR_BUCKET}"
    page_size = max(1, int(limit))
    offset = 0
    out: list[dict[str, Any]] = []
    while True:
        body = json.dumps({"prefix": prefix, "limit": page_size, "offset": offset}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "apikey": _anon_key(),
                "Authorization": f"Bearer {bearer_token}",
                "Content-Type": "application/json",
            },
        )
        result = _json_request(req)
        page = [row for row in result if isinstance(row, dict)] if isinstance(result, list) else []
        out.extend(page)
        if len(page) < page_size:
            break
        offset += page_size
        # Hard cap so a runaway list cannot loop forever.
        if offset >= 10_000:
            break
    return out


def delete_mirror_objects(
    *,
    user_id: str,
    profile_id: str,
    artifact_paths: list[str],
    bearer_token: str,
) -> list[str]:
    """Delete Storage objects under ``{uid}/{pid}/``. Returns deleted relative paths."""
    uid = (user_id or "").strip()
    pid = (profile_id or "").strip()
    if not uid or not pid:
        raise ValueError("invalid mirror delete scope")
    keys: list[str] = []
    rels: list[str] = []
    for raw in artifact_paths:
        rel = str(raw or "").strip().lstrip("/")
        if not rel or ".." in rel.split("/"):
            continue
        keys.append(mirror_object_key(uid, pid, rel))
        rels.append(rel)
    if not keys:
        return []
    url = f"{_base_url()}/storage/v1/object/{MIRROR_BUCKET}"
    body = json.dumps(keys).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="DELETE",
        headers={
            "apikey": _anon_key(),
            "Authorization": f"Bearer {bearer_token}",
            "Content-Type": "application/json",
        },
    )
    _json_request(req)
    return rels


def delete_mirror_snapshot_rows(
    *,
    user_id: str,
    profile_id: str,
    bearer_token: str,
    artifact_paths: list[str] | None = None,
) -> None:
    """Delete ``cloud_mirror_snapshots`` rows for a profile (optional path filter)."""
    uid = (user_id or "").strip()
    pid = (profile_id or "").strip()
    if not uid or not pid:
        raise ValueError("invalid mirror snapshot delete scope")
    params = [
        ("user_id", f"eq.{uid}"),
        ("profile_id", f"eq.{pid}"),
    ]
    if artifact_paths is not None:
        cleaned = [str(p).strip().lstrip("/") for p in artifact_paths if str(p).strip()]
        if not cleaned:
            return
        # PostgREST `in.(a,b)` — paths are allowlisted filenames, no commas.
        joined = ",".join(cleaned)
        params.append(("artifact_path", f"in.({joined})"))
    query = urllib.parse.urlencode(params)
    url = f"{_base_url()}/rest/v1/cloud_mirror_snapshots?{query}"
    req = urllib.request.Request(
        url,
        method="DELETE",
        headers={
            "apikey": _anon_key(),
            "Authorization": f"Bearer {bearer_token}",
            "Prefer": "return=minimal",
        },
    )
    _json_request(req)


def list_mirror_objects(*, user_id: str, profile_id: str, bearer_token: str, limit: int = 200) -> list[dict[str, Any]]:
    """Legacy single-prefix list (immediate children only). Prefer list_mirror_artifacts."""
    prefix = f"{user_id.strip()}/{profile_id.strip()}"
    return _list_prefix(prefix=prefix, bearer_token=bearer_token, limit=limit)


def list_mirror_profile_ids(*, user_id: str, bearer_token: str, limit: int = 200) -> list[str]:
    """List profile folder ids under ``{userId}/`` (non-recursive Storage list)."""
    from shared.profile_paths import is_valid_profile_id

    uid = (user_id or "").strip()
    if not uid:
        return []
    rows = _list_prefix(prefix=f"{uid}/", bearer_token=bearer_token, limit=limit)
    out: list[str] = []
    seen: set[str] = set()
    for row in rows:
        name = str(row.get("name") or "").strip().lstrip("/")
        if not name or "/" in name:
            continue
        if not is_valid_profile_id(name):
            continue
        if name in seen:
            continue
        seen.add(name)
        out.append(name)
    out.sort()
    return out


def list_mirror_artifacts(
    *, user_id: str, profile_id: str, bearer_token: str, limit: int = 200
) -> list[dict[str, Any]]:
    """List mirrorable files under ``{uid}/{pid}/``, including ``data/`` children.

    Supabase Storage ``object/list`` is not recursive: folder rows arrive with
    ``id: null``. We list the profile prefix and the ``data/`` subfolder and
    rejoin relative paths.
    """
    uid = user_id.strip()
    pid = profile_id.strip()
    base_prefix = f"{uid}/{pid}"
    out: dict[str, dict[str, Any]] = {}

    def _ingest(rows: list[dict[str, Any]], *, subdir: str = "") -> None:
        for row in rows:
            name = str(row.get("name") or "").strip().lstrip("/")
            if not name or name.endswith("/"):
                continue
            # Folder marker (no object id)
            if row.get("id") is None and "." not in name.split("/")[-1]:
                continue
            rel = f"{subdir}{name}" if not subdir else f"{subdir.rstrip('/')}/{name}"
            out[rel] = {
                "name": rel,
                "id": row.get("id"),
                "updated_at": row.get("updated_at"),
                "metadata": row.get("metadata"),
            }

    _ingest(_list_prefix(prefix=base_prefix, bearer_token=bearer_token, limit=limit))
    _ingest(
        _list_prefix(prefix=f"{base_prefix}/data", bearer_token=bearer_token, limit=limit),
        subdir="data",
    )
    return sorted(out.values(), key=lambda row: str(row.get("name") or ""))


def upsert_mirror_snapshot_row(
    *,
    user_id: str,
    profile_id: str,
    artifact_path: str,
    byte_size: int,
    bearer_token: str,
    device_id: str | None = None,
    revision: int | None = None,
) -> None:
    url = f"{_base_url()}/rest/v1/cloud_mirror_snapshots"
    payload: dict[str, Any] = {
        "user_id": user_id,
        "profile_id": profile_id,
        "artifact_path": artifact_path,
        "byte_size": byte_size,
        "device_id": device_id or mirror_device_id(),
    }
    if revision is not None:
        payload["revision"] = revision
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "apikey": _anon_key(),
            "Authorization": f"Bearer {bearer_token}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates",
        },
    )
    # Propagate so flush marks the artifact as error instead of silent "ok".
    _json_request(req)


def _json_request(req: urllib.request.Request) -> Any:
    try:
        with urllib.request.urlopen(req, timeout=_STORAGE_TIMEOUT_SEC) as resp:
            raw = resp.read().decode("utf-8")
            if not raw:
                return {}
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{req.method} {req.full_url} HTTP {exc.code}: {detail}") from exc
