"""Build-side dupe collapse (one row per strong group, sibling field merge)."""

from __future__ import annotations

from datetime import UTC, datetime

import fetchers.build_free_claims as bfc

NOW = datetime(2026, 10, 12, 12, 0, 0, tzinfo=UTC)


def _auto() -> list[dict]:
    return [
        {"id": "epic-foo", "source": "epic", "store": "epic", "title": "Foo",
         "claim_url": "https://store.epicgames.com/en-US/p/foo-abc123",
         "ends_at": "2026-10-15T15:00:00Z"},
        {"id": "gamerpower-1", "source": "gamerpower", "store": "epic",
         "title": "Foo (Epic Games) Giveaway", "claim_url": "https://gp.example/foo",
         "ends_at": "2026-10-15T23:59:00Z", "header_image": "https://gp.example/foo.jpg"},
        {"id": "itad-1", "source": "itad", "store": "epic",
         "title": "Foo - Free via EGS on Epic Game Store", "claim_url": "https://itad.example/1",
         "steam_appid": 42},
        {"id": "itad-2", "source": "itad", "store": "steam", "title": "Bar on Steam",
         "claim_url": "https://itad.example/2"},
    ]


def test_collapse_keeps_best_selected_member_and_merges_fields() -> None:
    auto = _auto()
    selected = [dict(auto[1]), dict(auto[2]), dict(auto[3])]
    out, dropped = bfc.collapse_dupe_groups(selected, auto)
    ids = [it["id"] for it in out]
    assert ids == ["gamerpower-1", "itad-2"]
    assert dropped == ["itad-1"]
    foo = out[0]
    assert foo["steam_appid"] == 42
    assert foo["ends_at"] == "2026-10-15T23:59:00Z"


def test_collapse_fills_lone_approved_loser_from_unapproved_siblings() -> None:
    auto = _auto()
    out, dropped = bfc.collapse_dupe_groups([dict(auto[2])], auto)
    assert dropped == []
    [row] = out
    assert row["id"] == "itad-1"
    assert row["ends_at"] == "2026-10-15T15:00:00Z"
    assert row["header_image"] == "https://gp.example/foo.jpg"


def test_collapse_respects_dupe_splits() -> None:
    auto = _auto()
    selected = [dict(auto[1]), dict(auto[2])]
    out, dropped = bfc.collapse_dupe_groups(
        selected, auto, splits=[["gamerpower-1", "itad-1"], ["epic-foo", "itad-1"]]
    )
    assert [it["id"] for it in out] == ["gamerpower-1", "itad-1"]
    assert dropped == []


def test_preview_publishes_one_card_per_dupe_group() -> None:
    items = bfc.preview_publish_items(
        manual_items=[],
        auto_items_all=_auto(),
        approved_ids={"epic-foo", "gamerpower-1", "itad-1", "itad-2"},
        now=NOW,
    )
    ids = sorted(it["id"] for it in items)
    assert ids == ["epic-foo", "itad-2"]


def test_prepare_approved_document_normalizes_dupe_splits() -> None:
    doc = bfc.prepare_approved_document(
        ids=[],
        store_overrides={},
        field_overrides={},
        premium_only_ids=set(),
        dismissed=[],
        auto_items=[],
        dupe_splits=[["b", "a"], ["a", "b"], ["c"], "junk"],
    )
    assert doc["dupe_splits"] == [["a", "b"]]
