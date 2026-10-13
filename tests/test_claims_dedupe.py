"""Cross-source dupe grouping (shared/claims_dedupe.py)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.claims_dedupe import (
    epic_slug_key,
    group_claims,
    groups_by_member,
    merge_group_fields,
    strong_loser_ids,
)

FIXTURE = Path(__file__).parent / "fixtures" / "claims_inbox_2026_10.json"


@pytest.fixture(scope="module")
def inbox() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_golden_inbox_finds_every_strong_group(inbox: dict) -> None:
    groups = [g for g in group_claims(inbox["items"]) if g.tier == "strong"]
    got = sorted(sorted(g.member_ids) for g in groups)
    want = sorted(sorted(g) for g in inbox["expected_groups"])
    assert got == want


def test_golden_inbox_triples_are_not_split_into_pairs(inbox: dict) -> None:
    groups = [g for g in group_claims(inbox["items"]) if g.tier == "strong"]
    sizes = sorted(len(g.member_ids) for g in groups)
    assert sizes.count(3) == 2
    assert sum(sizes) == 22


def test_golden_inbox_winners_follow_source_precedence(inbox: dict) -> None:
    by_member = groups_by_member(group_claims(inbox["items"]))
    for expected in inbox["expected_groups"]:
        assert by_member[expected[0]].winner_id == expected[0]


def test_golden_inbox_no_strong_false_positives(inbox: dict) -> None:
    grouped = set().union(*(set(g) for g in inbox["expected_groups"]))
    for g in group_claims(inbox["items"]):
        if g.tier == "strong":
            assert set(g.member_ids) <= grouped


def test_strong_loser_ids_excludes_winners(inbox: dict) -> None:
    groups = group_claims(inbox["items"])
    losers = strong_loser_ids(groups)
    assert "epic-out-of-sight-b96ca8" not in losers
    assert {"gamerpower-3806", "itad-fadc757d9c68"} <= losers
    assert len(losers) == 12


def _row(id_: str, source: str, title: str, **extra) -> dict:
    return {"id": id_, "source": source, "store": extra.pop("store", "steam"), "title": title, **extra}


def test_appid_links_rows_with_different_titles() -> None:
    items = [
        _row("gamerpower-1", "gamerpower", "Portal 2 (Steam) Giveaway", steam_appid=620),
        _row("itad-1", "itad", "Portal Two on Steam", steam_appid=620),
    ]
    [g] = group_claims(items)
    assert g.tier == "strong"
    assert g.winner_id == "gamerpower-1"
    assert "appid:620" in g.reasons


def test_triple_via_transitive_keys() -> None:
    items = [
        _row("epic-a", "epic", "Foo", steam_appid=1, store="epic"),
        _row("gamerpower-a", "gamerpower", "Foo (Epic Games) Giveaway", store="epic"),
        _row("itad-a", "itad", "Foo Game", steam_appid=1, store="epic"),
    ]
    [g] = group_claims(items)
    assert sorted(g.member_ids) == ["epic-a", "gamerpower-a", "itad-a"]
    assert g.winner_id == "epic-a"


def test_mobile_and_desktop_epic_never_merge() -> None:
    items = [
        _row("epic-a", "epic", "Foo", store="epic"),
        _row("epic-b", "epic", "Foo", store="epic_mobile"),
    ]
    assert group_claims(items) == []


def test_epic_slug_key_drops_hash_suffix() -> None:
    row = {"claim_url": "https://store.epicgames.com/en-US/p/out-of-sight-b96ca8"}
    assert epic_slug_key(row) == "epic:out-of-sight"


def test_epic_slug_links_rows_with_divergent_titles() -> None:
    items = [
        _row("epic-a", "epic", "Foo: The Game", store="epic",
             claim_url="https://store.epicgames.com/en-US/p/foo-abc123"),
        _row("gamerpower-a", "gamerpower", "Foo Remaster", store="epic",
             open_giveaway_url="https://store.epicgames.com/p/foo"),
    ]
    [g] = group_claims(items)
    assert g.tier == "strong"
    assert "epic:foo" in g.reasons


def test_edition_variant_is_possible_not_strong() -> None:
    items = [
        _row("gamerpower-1", "gamerpower", "Primal Slide (Steam) Giveaway"),
        _row("itad-1", "itad", "Primal Slide Deluxe Edition on Steam"),
    ]
    [g] = group_claims(items)
    assert g.tier == "possible"
    assert strong_loser_ids([g]) == set()


def test_shared_appid_across_dlc_title_is_possible() -> None:
    items = [
        _row("itad-1", "itad", "Rotwood", steam_appid=5),
        _row("itad-2", "itad", "Rotwood: Drakin Armoury Pack", steam_appid=5),
    ]
    [g] = group_claims(items)
    assert g.tier == "possible"


def test_dupe_splits_break_a_false_positive() -> None:
    items = [
        _row("gamerpower-1", "gamerpower", "Wordle (IndieGala) Giveaway"),
        _row("itad-1", "itad", "Wordle on IndieGala Store"),
    ]
    assert len(group_claims(items)) == 1
    assert group_claims(items, splits=[["gamerpower-1", "itad-1"]]) == []


def test_winner_prefers_ends_at_then_appid_within_same_source() -> None:
    items = [
        _row("itad-1", "itad", "Foo"),
        _row("itad-2", "itad", "Foo", steam_appid=9),
        _row("itad-3", "itad", "Foo", ends_at="2026-01-01T00:00:00Z"),
    ]
    [g] = group_claims(items)
    assert g.winner_id == "itad-3"


def test_merge_group_fields_fills_missing_from_siblings() -> None:
    winner = _row("epic-a", "epic", "Foo", store="epic")
    siblings = [
        _row("gamerpower-a", "gamerpower", "Foo", ends_at="2026-10-15T23:59:00Z",
             header_image="https://gp/x.jpg"),
        _row("itad-a", "itad", "Foo", ends_at="2026-10-15T15:00:00Z", steam_appid=42),
    ]
    merged = merge_group_fields(winner, [winner, *siblings])
    assert merged["ends_at"] == "2026-10-15T15:00:00Z"
    assert merged["steam_appid"] == 42
    assert merged["header_image"] == "https://gp/x.jpg"
    assert "ends_at" not in winner


def test_merge_group_fields_keeps_winner_values() -> None:
    winner = _row("epic-a", "epic", "Foo", ends_at="2026-10-20T00:00:00Z", steam_appid=1)
    merged = merge_group_fields(winner, [_row("itad-a", "itad", "Foo", ends_at="2026-10-10T00:00:00Z",
                                              steam_appid=2)])
    assert merged["ends_at"] == "2026-10-20T00:00:00Z"
    assert merged["steam_appid"] == 1
