"""Pro cloud read-only mirror — M1 upload scaffolding (disabled by default).

Debounced post-write hooks queue derived catalog artifacts for upload. M2 wires
Supabase Storage; until then uploads are stubbed (log-only) when gated on.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

from shared.entitlement import is_pro_background
from shared.pro_settings import read_pro_settings
from shared.profile_paths import get_active_profile_id, profile_root

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
    """True when Pro + opt-in toggle allow mirror work (M1 stub or M2 upload)."""
    if not is_pro_background():
        return False
    settings = read_pro_settings(profile_id=profile_id)
    if not settings.get("cloudMirrorEnabled"):
        return False
    return True


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
    """Upload (or stub) pending artifacts whose debounce window elapsed."""
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


def _flush_profile_uploads(profile_id: str, paths: set[str]) -> None:
    if not mirror_upload_allowed(profile_id=profile_id):
        return
    root = profile_root(profile_id=profile_id)
    payload = {
        "profile_id": profile_id,
        "artifacts": sorted(paths),
        "bytes": sum(_file_size(root / rel) for rel in paths),
    }
    if os.environ.get("BAKLOG_DEBUG"):
        print(f"[cloud_mirror] stub upload: {json.dumps(payload)}", file=sys.stderr, flush=True)
    # M2: upload to Supabase Storage bucket `baklog-mirror` per auth.uid().


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0
