"""Pro-tier background scheduler: refresh stale store libraries without the UI.

Server-side counterpart to the in-browser ``maybeAutoFetchStale24h`` loop. It
runs only for the paid ("pro") plan and only enqueues a fetch when a store's
catalog is older than the stale threshold — one store per stagger window —
coordinating with the existing single-slot :class:`RunManager` queue.

Unlike the browser loop (which needs an open dashboard tab), this keeps running
as long as the server process is alive, so a pro user gets background refresh
even when the app sits in the tray with no browser open.

Deal alerts: when the user opted in (``dealAlertsEnabled``), idle ticks that
found no stale library also refresh ITAD prices and the free games feed on
their own ``alert_stale_hours`` clock. With the opt-in off, no extra fetch is
ever queued. Every Pro tick ends with a cheap ``deal_alerts.scan()`` backstop
so CLI-started fetches still produce alerts.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shared.entitlement import is_pro_background
from shared.platform_support import platform_supported
from shared.profile_paths import (
    catalog_path,
    get_active_profile_id,
    personal_dir,
    runs_dir,
)

SCHEDULER_INTERVAL_SEC = 60.0
DEFAULT_STALE_AGE_SEC = 24 * 60 * 60
DEFAULT_STAGGER_SEC = 30 * 60
DEFAULT_PROBE_INTERVAL_SEC = 3600.0
# After an auth failure (exit 4) the scheduler can't re-auth headless, so back
# off this fetcher for a while and let the UI surface "reconnect needed".
AUTH_COOLDOWN_SEC = 60 * 60
DEFAULT_ALERT_STALE_SEC = 12 * 60 * 60
# Fetcher key -> the profile file whose ``fetched_at`` marks freshness.
ALERT_SOURCES = {"itad": "itad_prices.json", "claims": "free_claims.json"}


def _alerts_enabled(profile_id: str) -> bool:
    from shared.deal_alerts import alerts_enabled

    return alerts_enabled(profile_id)


def _scan_alerts(profile_id: str) -> None:
    from shared.deal_alerts import scan

    scan(profile_id)


def _as_epoch(value: Any) -> float | None:
    """Coerce a run timestamp (epoch float or ISO string) to epoch seconds."""
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


def _catalog_age_sec(meta_key: str, profile_id: str, now: float) -> float | None:
    """Seconds since the store catalog was fetched; None when never fetched."""
    return _file_age_sec(f"games_{meta_key}.json", profile_id, now)


def _file_age_sec(filename: str, profile_id: str, now: float) -> float | None:
    path = catalog_path(filename, profile_id=profile_id)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(doc, dict):
        return None
    fetched = _as_epoch(doc.get("fetched_at"))
    if fetched is None:
        return None
    return max(0.0, now - fetched)


class BackgroundScheduler:
    """Daemon thread that refreshes the stalest connected store for pro users."""

    def __init__(
        self,
        *,
        manager: Any,
        fetchers: dict[str, dict[str, Any]],
        missing_requirements: Callable[[list], list],
        interval_sec: float = SCHEDULER_INTERVAL_SEC,
        is_pro_fn: Callable[[], bool] = is_pro_background,
    ) -> None:
        self._manager = manager
        self._fetchers = fetchers
        self._missing_requirements = missing_requirements
        self._interval = interval_sec
        self._is_pro = is_pro_fn
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="bg-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        # Skip the first interval so boot-time fetches and orphan reaping settle.
        while not self._stop.wait(self._interval):
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001 - a bad tick must not kill the thread
                print(f"[scheduler] tick error: {exc!r}", file=sys.stderr, flush=True)

    # ---- one scheduling pass ----------------------------------------------
    def tick(self, *, now: float | None = None) -> str | None:
        """Run one pass. Returns the fetcher key enqueued this tick, else None."""
        if not self._is_pro():
            return None
        now = time.time() if now is None else now
        profile_id = get_active_profile_id()
        try:
            return self._schedule(profile_id, now)
        finally:
            try:
                _scan_alerts(profile_id)
            except Exception as exc:  # noqa: BLE001 - alerts must not kill the scheduler
                print(f"[scheduler] deal alert scan error: {exc!r}", file=sys.stderr, flush=True)

    def _schedule(self, profile_id: str, now: float) -> str | None:
        cfg = self._load_config(profile_id)
        if not cfg["enabled"]:
            return None
        if self._in_quiet_hours(cfg, now):
            return None

        self._maybe_probe_connections(profile_id, cfg, now)

        # One fetch per stagger window (mirrors the browser loop's 30 min stagger).
        library_due = now - self._load_state(profile_id, "last_run") >= cfg["stagger_sec"]
        alert_due = now - self._load_state(profile_id, "last_alert_run") >= cfg["stagger_sec"]
        if not library_due and not alert_due:
            return None

        # Single-slot queue: never pile onto an in-flight or queued run.
        snap = self._manager.snapshot()
        if snap.get("active") or snap.get("queue"):
            return None
        history = snap.get("history") or []

        if library_due:
            key = self._pick_stalest(profile_id, cfg, now, history)
            if key is not None:
                return self._submit(key, profile_id, now, "last_run", "background refresh")
        if alert_due:
            key = self._pick_stale_alert_source(profile_id, cfg, now, history)
            if key is not None:
                return self._submit(key, profile_id, now, "last_alert_run", "deal alert refresh")
        return None

    def _submit(self, key: str, profile_id: str, now: float, state_field: str, label: str) -> str | None:
        spec = self._fetchers[key]
        refresh = bool(spec.get("refreshArgs"))
        try:
            self._manager.submit(key, refresh=refresh)
        except (ValueError, KeyError):
            return None
        self._save_state(profile_id, state_field, now)
        print(f"[scheduler] {label} queued: {key}", file=sys.stderr, flush=True)
        return key

    def _pick_stale_alert_source(
        self,
        profile_id: str,
        cfg: dict[str, Any],
        now: float,
        history: list[dict[str, Any]],
    ) -> str | None:
        """Stalest of itad / claims when deal alerts are opted in, else None."""
        if not _alerts_enabled(profile_id):
            return None
        cooldown = self._auth_cooldown_keys(history, now)
        best_key: str | None = None
        best_age = -1.0
        for key, filename in ALERT_SOURCES.items():
            spec = self._fetchers.get(key)
            if spec is None or key in cooldown:
                continue
            if self._missing_requirements(spec.get("requires") or []):
                continue
            age = _file_age_sec(filename, profile_id, now)
            eff_age = float("inf") if age is None else age
            if eff_age < cfg["alert_stale_sec"]:
                continue
            if eff_age > best_age:
                best_age = eff_age
                best_key = key
        return best_key

    def _pick_stalest(
        self,
        profile_id: str,
        cfg: dict[str, Any],
        now: float,
        history: list[dict[str, Any]],
    ) -> str | None:
        cooldown = self._auth_cooldown_keys(history, now)
        best_key: str | None = None
        best_age = -1.0
        for key, spec in self._fetchers.items():
            if spec.get("group") != "library":
                continue
            if spec.get("autoFetch") is False:
                continue  # local launcher (GOG Galaxy, Amazon) — needs the app open
            if not platform_supported(spec.get("platforms")):
                continue
            if self._missing_requirements(spec.get("requires") or []):
                continue  # not connected / missing credentials
            if key in cooldown:
                continue
            age = _catalog_age_sec(spec.get("metaKey", key), profile_id, now)
            eff_age = float("inf") if age is None else age
            if eff_age < cfg["stale_age_sec"]:
                continue
            if eff_age > best_age:
                best_age = eff_age
                best_key = key
        return best_key

    def _maybe_probe_connections(self, profile_id: str, cfg: dict[str, Any], now: float) -> None:
        """Hourly silent connection health check (Pro only; never enqueues a fetch)."""
        from auth.connection_probe import probe_due, run_connection_probe

        interval = float(cfg.get("probe_interval_sec", DEFAULT_PROBE_INTERVAL_SEC))
        if not probe_due(profile_id, now, interval):
            return
        snap = self._manager.snapshot()
        history = snap.get("history") or []
        try:
            run_connection_probe(profile_id, now=now, history=history)
        except Exception as exc:  # noqa: BLE001 - probe must not kill the scheduler thread
            print(
                f"[scheduler] connection probe error: {exc!r}",
                file=sys.stderr,
                flush=True,
            )

    def _auth_cooldown_keys(self, history: list[dict[str, Any]], now: float) -> set[str]:
        out: set[str] = set()
        for h in history:
            if h.get("failure_kind") != "auth":
                continue
            ended = _as_epoch(h.get("ended_at"))
            if ended is None or now - ended < AUTH_COOLDOWN_SEC:
                key = h.get("key")
                if isinstance(key, str):
                    out.add(key)
        return out

    @staticmethod
    def _in_quiet_hours(cfg: dict[str, Any], now: float) -> bool:
        start = cfg.get("quiet_start_hour")
        end = cfg.get("quiet_end_hour")
        if not isinstance(start, int) or not isinstance(end, int) or start == end:
            return False
        hour = time.localtime(now).tm_hour
        if start < end:
            return start <= hour < end
        return hour >= start or hour < end  # window wraps midnight

    # ---- config + persisted state -----------------------------------------
    @staticmethod
    def _config_path(profile_id: str) -> Path:
        return personal_dir(profile_id=profile_id) / "scheduler.json"

    def _load_config(self, profile_id: str) -> dict[str, Any]:
        cfg: dict[str, Any] = {
            "enabled": True,
            "stale_age_sec": DEFAULT_STALE_AGE_SEC,
            "stagger_sec": DEFAULT_STAGGER_SEC,
            "probe_interval_sec": DEFAULT_PROBE_INTERVAL_SEC,
            "alert_stale_sec": DEFAULT_ALERT_STALE_SEC,
            "quiet_start_hour": None,
            "quiet_end_hour": None,
        }
        try:
            doc = json.loads(self._config_path(profile_id).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cfg
        if not isinstance(doc, dict):
            return cfg
        if isinstance(doc.get("enabled"), bool):
            cfg["enabled"] = doc["enabled"]
        hours = doc.get("stale_age_hours")
        if isinstance(hours, (int, float)) and hours > 0:
            cfg["stale_age_sec"] = float(hours) * 3600
        mins = doc.get("stagger_minutes")
        if isinstance(mins, (int, float)) and mins > 0:
            cfg["stagger_sec"] = float(mins) * 60
        probe_mins = doc.get("probe_interval_minutes")
        if isinstance(probe_mins, (int, float)) and probe_mins > 0:
            cfg["probe_interval_sec"] = float(probe_mins) * 60
        alert_hours = doc.get("alert_stale_hours")
        if isinstance(alert_hours, (int, float)) and alert_hours > 0:
            cfg["alert_stale_sec"] = float(alert_hours) * 3600
        for field in ("quiet_start_hour", "quiet_end_hour"):
            val = doc.get(field)
            if isinstance(val, int) and 0 <= val <= 23:
                cfg[field] = val
        return cfg

    @staticmethod
    def _state_path(profile_id: str) -> Path:
        return runs_dir(profile_id=profile_id) / "scheduler_state.json"

    def _read_state_doc(self, profile_id: str) -> dict[str, Any]:
        try:
            doc = json.loads(self._state_path(profile_id).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return doc if isinstance(doc, dict) else {}

    def _load_state(self, profile_id: str, field: str) -> float:
        try:
            return float(self._read_state_doc(profile_id).get(field, 0))
        except (TypeError, ValueError):
            return 0.0

    def _save_state(self, profile_id: str, field: str, ts: float) -> None:
        path = self._state_path(profile_id)
        doc = self._read_state_doc(profile_id)
        doc[field] = ts
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(doc), encoding="utf-8")
        except OSError:
            pass
