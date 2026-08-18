#!/usr/bin/env python3
"""Cursor stop hook: remind agent to update tracker.html after a session.

Always returning followup_message turns every agent stop into a new user turn.
Cursor's loop_limit is supposed to cap that, but other injected user messages
(e.g. background shell notifications) start a fresh stop cycle and reset the
count - the reminder then ping-pongs forever.

Honor loop_count, skip aborted stops, and remember the conversation id so this
conversation gets at most one reminder.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REMINDER = (
    "Session ending — if you completed meaningful work, update tracker.html: "
    "mark the relevant PHASES/findings entry [DONE] or [RESOLVED] with a dated note. "
    "See docs/WORKFLOW.md. Do not create PROGRESS.md. "
    "Direct-edit-first: when ..\\baklog-internal\\tracker.html exists, edit it there "
    "and run .\\scripts\\sync-internal-repo.ps1 -Push. "
    "Only if the internal clone is missing or editing is blocked (e.g. plan mode), "
    "write .cursor/tracker-pending-<slug>.md and run /apply-tracker-pending later."
)

TTL_SEC = 12 * 3600
ANON_TTL_SEC = 20 * 60


def state_path() -> Path:
    override = os.environ.get("BAKLOG_REMIND_TRACKER_STATE")
    if override:
        return Path(override)
    return Path(tempfile.gettempdir()) / "baklog-remind-tracker.json"


def _load_state(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_state(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def already_reminded(key: str, now: float, path: Path, ttl: int = TTL_SEC) -> bool:
    if not key:
        return False
    data = _load_state(path)
    ts = data.get(key)
    try:
        seen = float(ts)
    except (TypeError, ValueError):
        return False
    return (now - seen) < ttl


def mark_reminded(key: str, now: float, path: Path) -> None:
    data = _load_state(path)
    cutoff = now - TTL_SEC
    pruned = {k: v for k, v in data.items() if isinstance(v, (int, float)) and v >= cutoff}
    pruned[key] = now
    _save_state(path, pruned)


def conversation_key(payload: dict[str, Any]) -> str:
    for field in ("conversation_id", "conversationId", "session_id", "sessionId"):
        val = payload.get(field)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def should_remind(payload: dict[str, Any], *, now: float | None = None, path: Path | None = None) -> bool:
    """Return True when this stop should inject the tracker follow-up."""
    if (payload.get("status") or "") == "aborted":
        return False
    try:
        loop_count = int(payload.get("loop_count") or 0)
    except (TypeError, ValueError):
        loop_count = 0
    if loop_count > 0:
        return False
    stamp = time.time() if now is None else now
    store = path if path is not None else state_path()
    key = conversation_key(payload) or "__anon__"
    ttl = TTL_SEC if key != "__anon__" else ANON_TTL_SEC
    if already_reminded(key, stamp, store, ttl=ttl):
        return False
    mark_reminded(key, stamp, store)
    return True


def main() -> int:
    payload: dict[str, Any] = {}
    try:
        raw = json.load(sys.stdin)
        if isinstance(raw, dict):
            payload = raw
    except Exception:
        pass

    if should_remind(payload):
        print(json.dumps({"followup_message": REMINDER}), flush=True)
    else:
        print("{}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
