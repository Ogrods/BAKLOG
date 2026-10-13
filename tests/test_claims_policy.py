"""Trusted auto-publish policy (shared/claims_policy.py) against the Oct 2026 inbox."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from shared.claims_policy import (
    AUTO_PUBLISH,
    DISMISS_DUPE,
    OWNER,
    REVIEW,
    OwnerState,
    classify_inbox,
)

FIXTURE = Path(__file__).parent / "fixtures" / "claims_inbox_2026_10.json"
NOW = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)

# What the owner actually published on 2026-10-12 (PR 384).
OWNER_APPROVED_2026_10_12 = {
    "epic-out-of-sight-b96ca8",
    "epic-terrascape-2b12b1",
    "gamerpower-3328",
    "gamerpower-3498",
    "itad-6b4a0c098140",
    "itad-f99d00439cb6",
    "itad-538f08a31cd9",
}


@pytest.fixture(scope="module")
def items() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["items"]


def _actions(items, owner=None) -> dict[str, str]:
    return {c.id: c.action for c in classify_inbox(items, owner, now=NOW)}


def test_without_owner_epic_weekly_and_matched_steam_auto_publish(items) -> None:
    acts = _actions(items)
    auto = {i for i, a in acts.items() if a == AUTO_PUBLISH}
    assert auto == {
        "epic-out-of-sight-b96ca8",
        "epic-terrascape-2b12b1",
        "gamerpower-3810",  # Fireside Feelings (Steam, appid)
        "gamerpower-3809",  # Pony Island (Steam, appid)
    }


@pytest.mark.parametrize(
    "item_id, why",
    [
        ("gamerpower-3716", "key giveaway"),  # Dwarven Realms (Steam) Key
        ("itad-f99d00439cb6", "DLC or bonus content"),  # Rotwood: Drakin Armoury Pack
        ("itad-538f08a31cd9", "DLC or bonus content"),  # MXGP 26 liveries
        ("gamerpower-3322", "store other is not auto-trusted"),  # IndieGala
        ("gamerpower-3446", "store other is not auto-trusted"),  # Stove
        ("gamerpower-2204", "store itch is not auto-trusted"),
        ("itad-6b4a0c098140", None),  # The Big Con on Epic mobile via ITAD
    ],
)
def test_untrusted_rows_go_to_review(items, item_id: str, why: str | None) -> None:
    by_id = {c.id: c for c in classify_inbox(items, now=NOW)}
    assert by_id[item_id].action == REVIEW
    if why:
        assert by_id[item_id].reason == why


def test_every_strong_group_loser_is_dismissed(items) -> None:
    acts = _actions(items)
    dismissed = {i for i, a in acts.items() if a == DISMISS_DUPE}
    assert len(dismissed) == 12
    assert "gamerpower-3806" in dismissed and "itad-fadc757d9c68" in dismissed
    assert "epic-out-of-sight-b96ca8" not in dismissed


def test_owner_decisions_are_left_alone(items) -> None:
    owner = OwnerState(approved=set(OWNER_APPROVED_2026_10_12))
    acts = _actions(items, owner)
    for item_id in OWNER_APPROVED_2026_10_12:
        assert acts[item_id] == OWNER
    assert acts["itad-123db3b7378b"] == DISMISS_DUPE  # Best Plumber ITAD copy


def test_owner_approved_loser_becomes_keeper(items) -> None:
    owner = OwnerState(approved={"itad-4c479b8cc205"})  # owner picked the ITAD Fireside row
    by_id = {c.id: c for c in classify_inbox(items, owner, now=NOW)}
    assert by_id["itad-4c479b8cc205"].action == OWNER
    assert by_id["gamerpower-3810"].action == DISMISS_DUPE
    assert by_id["gamerpower-3810"].keeper_id == "itad-4c479b8cc205"


def test_owner_dismissed_winner_hands_keeper_to_next_copy(items) -> None:
    owner = OwnerState(dismissed={"epic-out-of-sight-b96ca8"})
    by_id = {c.id: c for c in classify_inbox(items, owner, now=NOW)}
    assert by_id["epic-out-of-sight-b96ca8"].action == OWNER
    assert by_id["gamerpower-3806"].keeper_id == "gamerpower-3806"
    assert by_id["gamerpower-3806"].action == REVIEW
    assert by_id["itad-fadc757d9c68"].action == DISMISS_DUPE


def test_owner_hid_every_copy(items) -> None:
    owner = OwnerState(blocked={"gamerpower-3809", "itad-4d6f2e0ae3da"})
    acts = _actions(items, owner)
    assert acts["gamerpower-3809"] == OWNER
    assert acts["itad-4d6f2e0ae3da"] == OWNER


def test_expired_steam_row_needs_review(items) -> None:
    later = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
    by_id = {c.id: c for c in classify_inbox(items, now=later)}
    assert by_id["gamerpower-3810"].action == REVIEW
    assert by_id["gamerpower-3810"].reason == "expired"


def test_premium_only_is_never_auto_published() -> None:
    row = {"id": "epic-x", "source": "epic", "store": "epic", "title": "X",
           "claim_url": "https://store.epicgames.com/p/x"}
    [c] = classify_inbox([row], OwnerState(premium_only={"epic-x"}), now=NOW)
    assert c.action == REVIEW


def test_possible_dupe_is_never_auto_published() -> None:
    rows = [
        {"id": "epic-x", "source": "epic", "store": "epic", "title": "Foo",
         "claim_url": "https://store.epicgames.com/p/foo"},
        {"id": "gamerpower-x", "source": "gamerpower", "store": "steam",
         "title": "Foo Deluxe Edition (Steam) Giveaway", "steam_appid": 5,
         "claim_url": "https://gp.example/foo"},
    ]
    acts = {c.id: (c.action, c.reason) for c in classify_inbox(rows, now=NOW)}
    assert acts["epic-x"] == (REVIEW, "possible duplicate")
    assert acts["gamerpower-x"][0] == REVIEW
