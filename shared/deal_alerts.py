"""Deal alert diff engine: wishlist price drops and new free claims.

Compares ``itad_prices.json`` and ``free_claims.json`` against a per-profile
snapshot in ``cache/deal_alerts.json`` and queues events for the tray to show.
Pure file logic, no HTTP or threads of its own. Public entry points never raise:
a broken alert must not fail a fetcher, the scheduler, or server boot.

Rules:
- First sight of a source seeds the snapshot and emits nothing.
- Event ids (``drop:<key>:<cents>``, ``claim:<sorted keys>``) are recorded in
  ``emitted`` so re-scanning the same files is inert.
- Only ``match == "appid"`` price rows alert (fuzzy title matches can be wrong
  and the ITAD lookup cache never expires).
- Pending is capped and expires, so a machine asleep for a month does not
  produce a wall of stale notifications.
"""

from __future__ import annotations

import json
import sys
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from shared.free_claims_sources import claim_match_keys
from shared.profile_paths import free_claims_path, itad_path, profile_cache_dir
from shared.safe_write import atomic_write_text

STATE_VERSION = 1
MAX_PENDING = 25
MAX_EMITTED = 200
MAX_SEEN_CLAIM_KEYS = 2000
PRICE_EVENT_TTL = timedelta(days=7)
# Same threshold as applyItadPriceSnapshot in js/deals.js.
DROP_EPSILON = 0.009

_LOCK = threading.Lock()

State = dict[str, Any]
Event = dict[str, Any]


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _log(msg: str) -> None:
    print(f"[deal_alerts] {msg}", file=sys.stderr, flush=True)


def state_path(profile_id: str | None = None) -> Path:
    return profile_cache_dir(profile_id=profile_id) / "deal_alerts.json"


def empty_state() -> State:
    return {
        "version": STATE_VERSION,
        "seeded_at": None,
        "seeded": {},
        "price_snapshot": {},
        "seen_claim_keys": [],
        "pending": [],
        "emitted": {},
    }


def _normalize(raw: Any) -> State:
    state = empty_state()
    if not isinstance(raw, dict) or raw.get("version") != STATE_VERSION:
        return state
    for key, kind in (
        ("seeded", dict),
        ("price_snapshot", dict),
        ("seen_claim_keys", list),
        ("pending", list),
        ("emitted", dict),
    ):
        if isinstance(raw.get(key), kind):
            state[key] = raw[key]
    if isinstance(raw.get("seeded_at"), str):
        state["seeded_at"] = raw["seeded_at"]
    state["pending"] = [e for e in state["pending"] if isinstance(e, dict) and e.get("id")]
    return state


def load_state(profile_id: str | None = None) -> State:
    """Read state; a missing or corrupt file rebuilds from empty."""
    path = state_path(profile_id)
    try:
        return _normalize(json.loads(path.read_text(encoding="utf-8")))
    except FileNotFoundError:
        return empty_state()
    except (OSError, ValueError) as exc:
        _log(f"state unreadable, starting fresh: {exc}")
        return empty_state()


def save_state(state: State, profile_id: str | None = None) -> None:
    path = state_path(profile_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(state, indent=2, ensure_ascii=False))


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _to_price(value: Any) -> float | None:
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    return price if price >= 0 else None


def _queue(state: State, event: Event) -> bool:
    if event["id"] in state["emitted"]:
        return False
    state["pending"].append(event)
    state["emitted"][event["id"]] = event["created_at"]
    return True


def scan_prices(state: State, itad_doc: dict | None, *, emit: bool = True, now: datetime | None = None) -> list[Event]:
    """Diff appid-matched ITAD rows against the snapshot; always refresh the snapshot."""
    by_key = itad_doc.get("by_key") if isinstance(itad_doc, dict) else None
    if not isinstance(by_key, dict):
        return []
    now = now or _now()
    snapshot: dict = state["price_snapshot"]
    events: list[Event] = []
    for key, row in by_key.items():
        if not isinstance(row, dict) or row.get("match") != "appid":
            continue
        price = _to_price(row.get("price"))
        if price is None:
            continue
        prev = snapshot.get(key)
        old = _to_price(prev.get("price")) if isinstance(prev, dict) else None
        snapshot[key] = {"price": price, "cut": row.get("cut")}
        if not emit or old is None or not price < old - DROP_EPSILON:
            continue
        event = {
            "id": f"drop:{key}:{round(price * 100)}",
            "kind": "price_drop",
            "key": key,
            "title": str(row.get("title") or "").strip(),
            "price": price,
            "was": old,
            "cut": row.get("cut"),
            "shop": row.get("shop"),
            "currency": row.get("currency"),
            "price_str": row.get("price_str"),
            "url": row.get("url"),
            "created_at": _iso(now),
        }
        if event["title"] and _queue(state, event):
            events.append(event)
    return events


def scan_claims(
    state: State,
    claims_doc: dict | None,
    *,
    pro: bool,
    emit: bool = True,
    now: datetime | None = None,
) -> list[Event]:
    """Queue claims whose stable match keys were never seen; always extend seen keys."""
    items = claims_doc.get("items") if isinstance(claims_doc, dict) else None
    if not isinstance(items, list):
        return []
    now = now or _now()
    seen: list = state["seen_claim_keys"]
    seen_set = set(seen)
    events: list[Event] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        keys = claim_match_keys(item)
        if not keys:
            continue
        is_new = seen_set.isdisjoint(keys)
        for k in sorted(keys - seen_set):
            seen.append(k)
            seen_set.add(k)
        if not emit or not is_new:
            continue
        if item.get("premium_only") and not pro:
            continue
        ends = _parse_iso(item.get("ends_at"))
        if ends is not None and ends <= now:
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        event = {
            "id": "claim:" + "|".join(sorted(keys)),
            "kind": "free_claim",
            "title": title,
            "store": item.get("store"),
            "ends_at": item.get("ends_at"),
            "claim_url": item.get("claim_url"),
            "created_at": _iso(now),
        }
        if _queue(state, event):
            events.append(event)
    if len(seen) > MAX_SEEN_CLAIM_KEYS:
        del seen[: len(seen) - MAX_SEEN_CLAIM_KEYS]
    return events


def _event_live(event: Event, now: datetime) -> bool:
    if event.get("kind") == "free_claim":
        ends = _parse_iso(event.get("ends_at"))
        return ends is None or ends > now
    created = _parse_iso(event.get("created_at"))
    return created is not None and now - created <= PRICE_EVENT_TTL


def trim(state: State, now: datetime | None = None) -> None:
    now = now or _now()
    pending = [e for e in state["pending"] if _event_live(e, now)]
    state["pending"] = pending[-MAX_PENDING:]
    emitted: dict = state["emitted"]
    if len(emitted) > MAX_EMITTED:
        newest = sorted(emitted.items(), key=lambda kv: str(kv[1]))[-MAX_EMITTED:]
        state["emitted"] = dict(newest)


def _default_pro() -> bool:
    try:
        from shared.entitlement import is_pro_background

        return bool(is_pro_background())
    except Exception:
        return False


def scan(profile_id: str | None = None, *, pro: bool | None = None, now: datetime | None = None) -> int:
    """Scan both sources and persist; returns the number of newly queued events."""
    try:
        now = now or _now()
        itad_doc = _read_json(itad_path(profile_id=profile_id))
        claims_doc = _read_json(free_claims_path(profile_id=profile_id))
        is_pro = _default_pro() if pro is None else pro
        with _LOCK:
            state = load_state(profile_id)
            seeded: dict = state["seeded"]
            queued = 0
            if itad_doc is not None:
                queued += len(scan_prices(state, itad_doc, emit="prices" in seeded, now=now))
                seeded.setdefault("prices", _iso(now))
            if claims_doc is not None:
                queued += len(scan_claims(state, claims_doc, pro=is_pro, emit="claims" in seeded, now=now))
                seeded.setdefault("claims", _iso(now))
            if seeded and not state["seeded_at"]:
                state["seeded_at"] = _iso(now)
            trim(state, now)
            save_state(state, profile_id)
            return queued
    except Exception as exc:
        _log(f"scan failed: {exc}")
        return 0


def take_pending(limit: int | None = None, profile_id: str | None = None) -> list[Event]:
    """Live pending events, oldest first. Does not remove them; call ack()."""
    try:
        with _LOCK:
            state = load_state(profile_id)
        now = _now()
        live = [e for e in state["pending"] if _event_live(e, now)]
        return live if limit is None else live[: max(0, limit)]
    except Exception as exc:
        _log(f"take_pending failed: {exc}")
        return []


def ack(ids: list[str], profile_id: str | None = None) -> int:
    """Remove acknowledged events from pending; returns how many were removed."""
    try:
        wanted = {str(i) for i in ids if i}
        if not wanted:
            return 0
        with _LOCK:
            state = load_state(profile_id)
            before = len(state["pending"])
            state["pending"] = [e for e in state["pending"] if e.get("id") not in wanted]
            removed = before - len(state["pending"])
            if removed:
                save_state(state, profile_id)
            return removed
    except Exception as exc:
        _log(f"ack failed: {exc}")
        return 0
