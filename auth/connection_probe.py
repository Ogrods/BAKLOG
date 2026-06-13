"""Silent connection health probes for Pro-tier background scheduling.

Verifies cheap/no-browser sessions without enqueueing a fetch or touching catalogs.
After two consecutive auth rejections, flips the connection status light to
``expired`` via :func:`auth.manager.mark_invalid`.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from auth.manager import _with_profile_secrets, get_status, mark_invalid, mark_verified
from auth.session_probe import PROBEABLE_QUIET, probe_provider_quiet
from fetchers.registry import AUTH_PROVIDER_BY_KEY
from shared.profile_paths import runs_dir

STRIKE_THRESHOLD = 2
PROBE_INTERVAL_SEC = 3600
AUTH_COOLDOWN_SEC = 60 * 60


def _as_epoch(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            txt = value.strip().replace("Z", "+00:00")
            dt = datetime.fromisoformat(txt)
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.timestamp()
    return None


def _state_path(profile_id: str) -> Path:
    return runs_dir(profile_id=profile_id) / "connection_probe_state.json"


def load_probe_state(profile_id: str) -> dict[str, Any]:
    path = _state_path(profile_id)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"last_probe": 0.0, "strikes": {}}
    if not isinstance(doc, dict):
        return {"last_probe": 0.0, "strikes": {}}
    strikes = doc.get("strikes")
    if not isinstance(strikes, dict):
        strikes = {}
    try:
        last_probe = float(doc.get("last_probe", 0))
    except (TypeError, ValueError):
        last_probe = 0.0
    return {"last_probe": last_probe, "strikes": dict(strikes)}


def save_probe_state(profile_id: str, state: dict[str, Any]) -> None:
    path = _state_path(profile_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def clear_probe_strike(profile_id: str, provider: str) -> None:
    """Drop accumulated auth-fail strikes after a successful reconnect."""
    if provider not in PROBEABLE_QUIET:
        return
    state = load_probe_state(profile_id)
    strikes = state.get("strikes")
    if not isinstance(strikes, dict) or provider not in strikes:
        return
    strikes = dict(strikes)
    del strikes[provider]
    state["strikes"] = strikes
    save_probe_state(profile_id, state)


def probe_due(profile_id: str, now: float, interval_sec: float = PROBE_INTERVAL_SEC) -> bool:
    """True when the hourly cadence allows another probe pass."""
    state = load_probe_state(profile_id)
    last = float(state.get("last_probe", 0))
    return now - last >= interval_sec


def providers_in_auth_cooldown(
    history: list[dict[str, Any]],
    now: float,
    *,
    cooldown_sec: float = AUTH_COOLDOWN_SEC,
) -> set[str]:
    """Provider keys to skip after a recent fetcher auth failure."""
    out: set[str] = set()
    for entry in history:
        if entry.get("failure_kind") != "auth":
            continue
        ended = _as_epoch(entry.get("ended_at"))
        if ended is None or now - ended >= cooldown_sec:
            continue
        key = entry.get("key")
        if not isinstance(key, str):
            continue
        provider = AUTH_PROVIDER_BY_KEY.get(key)
        if provider:
            out.add(provider)
    return out


def _load_history(profile_id: str) -> list[dict[str, Any]]:
    path = runs_dir(profile_id=profile_id) / "history.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def run_connection_probe(
    profile_id: str,
    *,
    now: float | None = None,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, str]:
    """Probe connected cheap providers; update status light only (no fetch).

    Returns per-provider outcomes: ``ok``, ``auth_fail``, ``unreachable``,
    or ``skipped_cooldown``. Providers not currently ``connected`` are omitted.
    """
    now = time.time() if now is None else now
    if history is None:
        history = _load_history(profile_id)

    cooldown = providers_in_auth_cooldown(history, now)
    state = load_probe_state(profile_id)
    strikes: dict[str, int] = {
        k: int(v) for k, v in (state.get("strikes") or {}).items() if isinstance(v, (int, float))
    }
    results: dict[str, str] = {}
    probed = False

    with _with_profile_secrets(profile_id):
        status_by_key = {row["key"]: row for row in get_status()}
        for provider in sorted(PROBEABLE_QUIET):
            row = status_by_key.get(provider)
            if not row or row.get("status") != "connected":
                continue
            if provider in cooldown:
                results[provider] = "skipped_cooldown"
                continue

            outcome = probe_provider_quiet(provider)
            results[provider] = outcome
            probed = True

            if outcome == "ok":
                strikes[provider] = 0
                mark_verified(provider)
            elif outcome == "auth_fail":
                count = strikes.get(provider, 0) + 1
                strikes[provider] = count
                if count >= STRIKE_THRESHOLD:
                    mark_invalid(provider, error="Session rejected by provider")
                    strikes[provider] = 0
            # unreachable: leave strikes and status untouched

    state["strikes"] = strikes
    if probed:
        state["last_probe"] = now
    save_probe_state(profile_id, state)
    return results
