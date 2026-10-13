"""Expiry rule for free-claim rows that have no ``ends_at``.

Shared by the feed build, the admin preview and the autopilot digest so all
three agree on when an undated claim stops being publishable.

- ITAD and other sources keep listing giveaways after they end, so an undated
  row expires ``DEFAULT_EXPIRY_DAYS`` after ``first_seen``.
- The GamerPower API only lists active giveaways, so an undated GamerPower row
  stays live while ``last_seen`` (stamped by each successful fetch) is within
  ``LIVE_LISTING_WINDOW``. Rows carried forward from a failed fetch keep their
  old stamp, so an outage cannot fake liveness.

Sync pair: ``admin/claims-workspace.js`` ``isTrustedLiveListing`` /
``needsApproveEndDate`` (parity vectors in ``tests/fixtures/claims_expiry.json``).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

DEFAULT_EXPIRY_DAYS = 14
LIVE_LISTING_WINDOW = timedelta(hours=36)
LIVE_LISTING_SOURCES = frozenset({"gamerpower"})


def parse_dt(value: object) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def iso_z(dt: datetime) -> str:
    return dt.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def has_ends_at(item: dict) -> bool:
    ends = item.get("ends_at")
    return ends is not None and bool(str(ends).strip())


def is_trusted_live_listing(item: dict, now: datetime) -> bool:
    """True for an undated row from a live-only source seen in a recent fetch."""
    source = str(item.get("source") or "").strip().lower()
    if source not in LIVE_LISTING_SOURCES:
        return False
    last_seen = parse_dt(item.get("last_seen"))
    if last_seen is None:
        return False
    return now - last_seen <= LIVE_LISTING_WINDOW


def default_ends_at(item: dict, now: datetime | None = None) -> str | None:
    """Assumed end for an undated row, or None when it should never expire.

    ``now`` enables the live-listing trust; without it only the
    ``first_seen + DEFAULT_EXPIRY_DAYS`` rule applies.
    """
    if now is not None and is_trusted_live_listing(item, now):
        return None
    first_seen = parse_dt(item.get("first_seen"))
    if first_seen is None:
        return None
    return iso_z(first_seen + timedelta(days=DEFAULT_EXPIRY_DAYS))


def effective_ends_at(item: dict, now: datetime | None = None) -> object:
    """``ends_at`` when set, else the assumed default (see ``default_ends_at``)."""
    if has_ends_at(item):
        return item.get("ends_at")
    return default_ends_at(item, now)


def is_expired(item: dict, now: datetime) -> bool:
    parsed = parse_dt(effective_ends_at(item, now))
    return parsed is not None and parsed < now


def needs_approve_end_date(item: dict, now: datetime) -> bool:
    """True when approving this row as-is would be undone by the build's prune."""
    if has_ends_at(item):
        return False
    return is_expired(item, now)


def approve_end_date(now: datetime) -> str:
    """End date an owner approval assigns to a stale undated row."""
    return iso_z(now + timedelta(days=DEFAULT_EXPIRY_DAYS))
