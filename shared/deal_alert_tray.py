"""Tray side of deal alerts: notification text and the "Snooze alerts today" file.

Pure helpers (no pystray, no HTTP) so they are testable and the tray stays
small. Strings here are user-visible: no em dashes (AGENTS.md rule 8).
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

# Windows toast limits are roughly 64 characters of title and 256 of body.
TITLE_MAX = 64
BODY_MAX = 256
MAX_NAMED = 3

_SNOOZE_FILE = "deal-alerts-snooze.json"

STORE_LABELS = {
    "epic": "Epic",
    "epic_mobile": "Epic mobile",
    "gog": "GOG",
    "steam": "Steam",
    "prime": "Prime Gaming",
    "amazon": "Prime Gaming",
    "ubisoft": "Ubisoft",
    "humble": "Humble",
    "itch": "itch.io",
    "xbox": "Xbox",
    "psn": "PlayStation",
}


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _store_label(store: Any) -> str:
    key = str(store or "").strip().lower()
    return STORE_LABELS.get(key, key.replace("_", " ").title())


def _price_text(alert: dict) -> str:
    price_str = str(alert.get("price_str") or "").strip()
    if price_str:
        return price_str
    try:
        price = float(alert.get("price"))
    except (TypeError, ValueError):
        return ""
    currency = str(alert.get("currency") or "").strip()
    return f"{price:.2f} {currency}".strip()


def _short_date(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return ""
    if dt.tzinfo is not None:
        dt = dt.astimezone()
    return f"{dt.strftime('%b')} {dt.day}"


def _names(alerts: list[dict]) -> str:
    titles = [str(a.get("title") or "").strip() for a in alerts]
    titles = [t for t in titles if t]
    shown = ", ".join(titles[:MAX_NAMED])
    extra = len(titles) - MAX_NAMED
    return f"{shown} and {extra} more" if extra > 0 else shown


def _drop_message(drops: list[dict]) -> tuple[str, str]:
    if len(drops) > 1:
        return f"{len(drops)} wishlist price drops", f"{_names(drops)}. Open BAKLOG for details."
    alert = drops[0]
    title = str(alert.get("title") or "A wishlist game").strip()
    cut = alert.get("cut")
    shop = str(alert.get("shop") or "").strip()
    price = _price_text(alert)
    body = f"{title} is {int(cut)}% off" if isinstance(cut, (int, float)) and cut > 0 else f"{title} dropped in price"
    if shop:
        body += f" at {shop}"
    if price:
        body += f" ({price})"
    return "Wishlist price drop", f"{body}. Open BAKLOG for details."


def _claim_message(claims: list[dict]) -> tuple[str, str]:
    if len(claims) > 1:
        return f"{len(claims)} new free games", f"{_names(claims)}. Open BAKLOG to claim."
    alert = claims[0]
    title = str(alert.get("title") or "A game").strip()
    body = f"{title} is free"
    store = _store_label(alert.get("store"))
    if store:
        body += f" on {store}"
    until = _short_date(alert.get("ends_at"))
    if until:
        body += f" until {until}"
    return "New free game", f"{body}. Open BAKLOG to claim."


def compose_notifications(alerts: list[dict]) -> list[tuple[str, str]]:
    """At most two (title, body) pairs per cycle: price drops first, then free games."""
    drops = [a for a in alerts if isinstance(a, dict) and a.get("kind") == "price_drop"]
    claims = [a for a in alerts if isinstance(a, dict) and a.get("kind") == "free_claim"]
    out: list[tuple[str, str]] = []
    if drops:
        out.append(_drop_message(drops))
    if claims:
        out.append(_claim_message(claims))
    return [(_clip(t, TITLE_MAX), _clip(b, BODY_MAX)) for t, b in out]


def snooze_path(data_root: Path) -> Path:
    return data_root / _SNOOZE_FILE


def is_snoozed(data_root: Path, today: date | None = None) -> bool:
    try:
        raw = json.loads(snooze_path(data_root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    day = raw.get("snoozed_on") if isinstance(raw, dict) else None
    return day == (today or date.today()).isoformat()


def set_snoozed(data_root: Path, snoozed: bool, today: date | None = None) -> None:
    path = snooze_path(data_root)
    if not snoozed:
        path.unlink(missing_ok=True)
        return
    data_root.mkdir(parents=True, exist_ok=True)
    payload = {"snoozed_on": (today or date.today()).isoformat()}
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
