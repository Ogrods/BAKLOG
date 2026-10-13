"""Trusted auto-publish policy for the claims autopilot.

Owner preference (Oct 2026): auto-publish only high-confidence claims, auto
dismiss strong dupes, and leave everything else for review.

**auto_publish** (all must hold on the group keeper, after sibling field merge):

- Official Epic weekly API row (``source == "epic"``, store ``epic``), or
- Steam free-to-keep with a matched ``steam_appid`` (``store == "steam"``).
- Not a key giveaway, DLC / bonus / pack drop, or Pro-only claim.
- Has a valid outbound claim link and is not already expired.

**dismiss_dupe**: non-keeper members of a strong dupe group.

**review**: everything else (IndieGala, Stove, itch, GOG, keys, DLC, possible
dupes, missing appid).

**owner**: the owner already decided this row; autopilot leaves it alone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from shared.claims_dedupe import ClaimGroup, group_claims, merge_group_fields, pick_winner
from shared.free_claims_sources import has_valid_claim_links

AUTO_PUBLISH = "auto_publish"
REVIEW = "review"
DISMISS_DUPE = "dismiss_dupe"
OWNER = "owner"

_BONUS_RE = re.compile(
    r"\b(dlc|add-?on|soundtrack|ost|bonus|skin|skins|loot|pack|liveries|livery|"
    r"in-?game|currency|cosmetic|artbook|wallpaper)\b",
    re.IGNORECASE,
)
_KEY_GIVEAWAY_RE = re.compile(r"\bkey\b", re.IGNORECASE)


@dataclass
class OwnerState:
    approved: set[str] = field(default_factory=set)
    dismissed: set[str] = field(default_factory=set)
    blocked: set[str] = field(default_factory=set)
    dismissed_item_ids: set[str] = field(default_factory=set)
    premium_only: set[str] = field(default_factory=set)

    def decided(self, item_id: str) -> bool:
        return item_id in self.approved or self.said_no(item_id)

    def said_no(self, item_id: str) -> bool:
        return (
            item_id in self.dismissed
            or item_id in self.blocked
            or item_id in self.dismissed_item_ids
        )


@dataclass
class Classification:
    id: str
    action: str
    reason: str
    group_key: str | None = None
    keeper_id: str | None = None


def _parse_dt(value: object) -> datetime | None:
    s = str(value or "").strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def trusted_reason(item: dict, *, now: datetime, owner: OwnerState | None = None) -> str | None:
    """Why ``item`` qualifies for auto-publish, or None when it needs review."""
    item_id = str(item.get("id") or "")
    if owner and item_id in owner.premium_only:
        return None
    title = str(item.get("title") or "")
    if _BONUS_RE.search(title) or _KEY_GIVEAWAY_RE.search(title):
        return None
    if not has_valid_claim_links(item):
        return None
    ends = _parse_dt(item.get("ends_at"))
    if ends is not None and ends <= now:
        return None
    source = str(item.get("source") or "").lower()
    store = str(item.get("store") or "").lower()
    if source == "epic" and store == "epic":
        return "official Epic weekly free game"
    if store == "steam" and item.get("steam_appid"):
        return "Steam free-to-keep with matched app id"
    return None


def review_reason(item: dict, *, now: datetime | None = None) -> str:
    title = str(item.get("title") or "")
    store = str(item.get("store") or "").lower()
    ends = _parse_dt(item.get("ends_at"))
    if now is not None and ends is not None and ends <= now:
        return "expired"
    if _KEY_GIVEAWAY_RE.search(title):
        return "key giveaway"
    if _BONUS_RE.search(title):
        return "DLC or bonus content"
    if not has_valid_claim_links(item):
        return "missing claim link"
    if store == "steam" and not item.get("steam_appid"):
        return "Steam row without a matched app id"
    if store == "epic_mobile":
        return "Epic mobile"
    return f"store {store or 'unknown'} is not auto-trusted"


def classify_inbox(
    items: list[dict],
    owner: OwnerState | None = None,
    *,
    splits: list[list[str]] | None = None,
    now: datetime | None = None,
    groups: list[ClaimGroup] | None = None,
) -> list[Classification]:
    """Classify every inbox row. Output order follows ``items``."""
    owner = owner or OwnerState()
    now = now or datetime.now(UTC)
    rows = [it for it in items if isinstance(it, dict) and str(it.get("id") or "").strip()]
    by_id = {str(it["id"]).strip(): it for it in rows}
    if groups is None:
        groups = group_claims(rows, splits=splits)
    strong = [g for g in groups if g.tier == "strong"]
    possible_ids = {m for g in groups if g.tier == "possible" for m in g.member_ids}

    out: dict[str, Classification] = {}
    for g in strong:
        members = [by_id[m] for m in g.member_ids if m in by_id]
        approved = [m for m in members if str(m["id"]) in owner.approved]
        live = [m for m in members if not owner.said_no(str(m["id"]))]
        if approved:
            keeper = pick_winner(approved)
        elif live:
            keeper = pick_winner(live)
        else:
            for m in members:
                out[str(m["id"])] = Classification(
                    str(m["id"]), OWNER, "owner hid every copy", g.key, None
                )
            continue
        keeper_id = str(keeper["id"])
        for m in members:
            mid = str(m["id"])
            if mid == keeper_id:
                continue
            if owner.decided(mid) and mid not in owner.approved:
                out[mid] = Classification(mid, OWNER, "owner decision", g.key, keeper_id)
            else:
                out[mid] = Classification(
                    mid, DISMISS_DUPE, f"duplicate of {keeper_id}", g.key, keeper_id
                )
        if owner.decided(keeper_id):
            out[keeper_id] = Classification(keeper_id, OWNER, "owner decision", g.key, keeper_id)
            continue
        merged = merge_group_fields(keeper, members)
        why = trusted_reason(merged, now=now, owner=owner)
        if why and keeper_id not in possible_ids:
            out[keeper_id] = Classification(keeper_id, AUTO_PUBLISH, why, g.key, keeper_id)
        else:
            reason = "possible duplicate" if keeper_id in possible_ids else review_reason(merged, now=now)
            out[keeper_id] = Classification(keeper_id, REVIEW, reason, g.key, keeper_id)

    for it in rows:
        iid = str(it["id"]).strip()
        if iid in out:
            continue
        if owner.decided(iid):
            out[iid] = Classification(iid, OWNER, "owner decision")
            continue
        why = trusted_reason(it, now=now, owner=owner)
        if why and iid not in possible_ids:
            out[iid] = Classification(iid, AUTO_PUBLISH, why)
        else:
            reason = "possible duplicate" if iid in possible_ids else review_reason(it, now=now)
            out[iid] = Classification(iid, REVIEW, reason)

    return [out[str(it["id"]).strip()] for it in rows]
