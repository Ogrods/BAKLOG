"""Autopilot decisions (``auto_decisions.json``) and how they merge with owner state.

Merge order (first match wins):

1. Owner ``blocked`` / ``dismissed`` (ids or keys) - the owner said no.
2. Owner ``ids`` (approved) - the owner said yes; an auto dismissal cannot hide it.
3. Autopilot ``approve`` / ``dismiss``.

Auto dupe dismissals carry a source-scoped match key (``itad|title:foo``) in
addition to the id, so a loser keeps being hidden after its feed id churns,
without also hiding the winner that shares the same title key.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from shared.free_claims_sources import claim_match_keys

AUTO_DECISIONS_VERSION = 1


def empty_auto_decisions() -> dict:
    return {
        "version": AUTO_DECISIONS_VERSION,
        "updated_at": None,
        "approve": [],
        "dismiss": [],
        "dismissed_match_keys": [],
        "decisions": {},
    }


def load_auto_decisions(path: Path | None) -> dict:
    if path is None or not Path(path).is_file():
        return empty_auto_decisions()
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_auto_decisions()
    if not isinstance(doc, dict):
        return empty_auto_decisions()
    out = empty_auto_decisions()
    for key in ("approve", "dismiss", "dismissed_match_keys"):
        raw = doc.get(key)
        if isinstance(raw, list):
            out[key] = [str(x).strip() for x in raw if str(x).strip()]
    if isinstance(doc.get("decisions"), dict):
        out["decisions"] = doc["decisions"]
    out["updated_at"] = doc.get("updated_at")
    return out


def scoped_match_keys(item: dict) -> set[str]:
    source = str(item.get("source") or "").strip().lower() or "unknown"
    return {f"{source}|{k}" for k in claim_match_keys(item)}


@dataclass
class MergedDecisions:
    approved_ids: set[str]
    dismissed_ids: set[str]
    auto_approved: set[str] = field(default_factory=set)
    auto_dismissed: set[str] = field(default_factory=set)


def merge_decisions(
    *,
    owner_approved: set[str],
    owner_dismissed: set[str],
    auto: dict,
    auto_items: list[dict],
    owner_dismissed_item_ids: set[str] | None = None,
) -> MergedDecisions:
    """Fold autopilot decisions under owner decisions.

    ``owner_dismissed`` already includes blocked ids. ``owner_dismissed_item_ids``
    are feed ids the owner hid by key (title-key dismissals), resolved by the caller.
    """
    owner_no = set(owner_dismissed) | set(owner_dismissed_item_ids or ())
    auto_dismiss = {i for i in auto.get("dismiss") or [] if i}
    dismissed_keys = set(auto.get("dismissed_match_keys") or [])
    if dismissed_keys:
        for it in auto_items:
            item_id = str(it.get("id") or "").strip()
            if item_id and scoped_match_keys(it) & dismissed_keys:
                auto_dismiss.add(item_id)
    auto_dismiss -= owner_approved
    auto_approve = {i for i in auto.get("approve") or [] if i}
    auto_approve -= owner_no
    auto_approve -= auto_dismiss
    auto_approve -= owner_approved
    return MergedDecisions(
        approved_ids=set(owner_approved) | auto_approve,
        dismissed_ids=set(owner_dismissed) | (auto_dismiss - owner_approved),
        auto_approved=auto_approve,
        auto_dismissed=auto_dismiss - set(owner_dismissed),
    )
