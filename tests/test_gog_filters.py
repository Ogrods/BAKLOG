"""Tests for shared GOG name filters (gog_filters.py)."""

from __future__ import annotations

import fetch_gog as fg
from gog_filters import (
    apply_gog_name_filters,
    collapse_metadata_barren_dupes,
    collapse_pack_dupes,
    filter_gog_game_rows,
    should_skip_gog_title,
)


def test_should_skip_voucher_and_name_dlc() -> None:
    assert should_skip_gog_title("Freedom to buy games")
    assert should_skip_gog_title("Brigador: Deluxe DLC Upgrade")
    assert not should_skip_gog_title("Ashworld")


def test_build_game_row_skips_non_game_title() -> None:
    row = fg._build_game_row(
        {"id": 1, "title": "Freedom to buy games", "mediaType": 1},
        None,
        None,
    )
    assert row is None


def test_build_game_row_skips_non_game_media_type() -> None:
    row = fg._build_game_row(
        {"id": 2, "title": "Soundtrack", "mediaType": 3},
        None,
        None,
    )
    assert row is None


def test_forgotten_realms_pack_dropped_when_components_present() -> None:
    rows = [
        {"name": "Forgotten Realms: The Archives - Collection One", "gog_id": 1},
        {"name": "Eye of the Beholder", "gog_id": 2},
        {"name": "Eye of the Beholder II: The Legend of Darkmoon", "gog_id": 3},
        {"name": "Eye of the Beholder III: Assault on Myth Drannor", "gog_id": 4},
    ]
    out = collapse_pack_dupes(rows)
    assert len(out) == 3
    assert all("Collection One" not in r["name"] for r in out)


def test_post_merge_drops_pack_with_different_gog_id() -> None:
    games = [
        {"name": "Silver Box Classics", "gog_id": 9001, "source": "web"},
        {"name": "Heroes of the Lance", "gog_id": 9002, "source": "local"},
        {"name": "Dragons of Flame", "gog_id": 9003, "source": "local"},
        {"name": "War of the Lance", "gog_id": 9004, "source": "local"},
        {"name": "Shadow Sorcerer", "gog_id": 9005, "source": "local"},
    ]
    out = filter_gog_game_rows(games)
    assert len(out) == 4
    assert not any(g["gog_id"] == 9001 for g in out)


def test_apply_promo_collapse_on_web_style_rows() -> None:
    rows = [
        {"name": "Ashworld", "gog_id": 1},
        {"name": "Ashworld - Amazon Luna", "gog_id": 2},
    ]
    out = apply_gog_name_filters(rows)
    assert len(out) == 1
    assert out[0]["gog_id"] == 1


def test_prime_giveaway_dropped_when_populated_twin_exists() -> None:
    rows = [
        {
            "name": "XCOM® 2",
            "gog_id": 1482002159,
            "header_image": "https://images.gog.com/xcom2.jpg",
            "genres": ["Strategy"],
        },
        {
            "name": "XCOM® 2 - Prime Giveaway",
            "gog_id": 1259310057,
            "header_image": None,
            "genres": [],
        },
    ]
    out = apply_gog_name_filters(rows)
    assert len(out) == 1
    assert out[0]["gog_id"] == 1482002159


def test_exact_name_barren_duplicate_dropped() -> None:
    rows = [
        {
            "name": "Mafia II: Definitive Edition",
            "gog_id": 1449710114,
            "header_image": "https://images.gog.com/mafia.jpg",
            "genres": ["Adventure"],
        },
        {
            "name": "Mafia II: Definitive Edition",
            "gog_id": 1943447848,
            "header_image": None,
            "genres": [],
        },
    ]
    out = collapse_metadata_barren_dupes(rows)
    assert len(out) == 1
    assert out[0]["gog_id"] == 1449710114


def test_year_qualifier_barren_duplicate_dropped() -> None:
    rows = [
        {
            "name": "Legacy of Kain: Defiance (2003)",
            "gog_id": 1207659088,
            "header_image": "https://images.gog.com/lok.jpg",
            "genres": ["Adventure"],
        },
        {
            "name": "Legacy of Kain: Defiance",
            "gog_id": 2042523187,
            "header_image": None,
            "genres": [],
        },
    ]
    out = collapse_metadata_barren_dupes(rows)
    assert len(out) == 1
    assert out[0]["gog_id"] == 1207659088


def test_populated_sequels_not_collapsed() -> None:
    rows = [
        {
            "name": "DOOM 3",
            "gog_id": 1,
            "header_image": "https://images.gog.com/doom3.jpg",
            "genres": ["Shooter"],
        },
        {
            "name": "DOOM 3: BFG Edition",
            "gog_id": 2,
            "header_image": "https://images.gog.com/doom3bfg.jpg",
            "genres": ["Shooter"],
        },
    ]
    out = collapse_metadata_barren_dupes(rows)
    assert len(out) == 2


def test_barren_solo_kept() -> None:
    rows = [
        {
            "name": "Stray Gods: Orpheus Edition",
            "gog_id": 1098723469,
            "header_image": None,
            "genres": [],
        },
    ]
    out = collapse_metadata_barren_dupes(rows)
    assert len(out) == 1
    assert out[0]["gog_id"] == 1098723469


def test_edition_variant_barren_dropped_when_populated_sibling_exists() -> None:
    rows = [
        {
            "name": "Stray Gods: The Roleplaying Musical",
            "gog_id": 1624007757,
            "header_image": "https://images.gog.com/stray.jpg",
            "genres": ["Adventure"],
        },
        {
            "name": "Stray Gods: Orpheus Edition",
            "gog_id": 1098723469,
            "header_image": None,
            "genres": [],
        },
    ]
    out = apply_gog_name_filters(rows)
    assert len(out) == 1
    assert out[0]["gog_id"] == 1624007757


def test_brigador_deluxe_barren_dropped_when_edition_populated() -> None:
    rows = [
        {
            "name": "Brigador: Up-Armored Edition",
            "gog_id": 1356485086,
            "header_image": "https://images.gog.com/brig.jpg",
            "genres": ["Action"],
        },
        {
            "name": "Brigador: Up-Armored Deluxe",
            "gog_id": 1744995009,
            "header_image": None,
            "genres": [],
        },
    ]
    out = apply_gog_name_filters(rows)
    assert len(out) == 1
    assert out[0]["gog_id"] == 1356485086


def test_alone_in_the_dark_trilogy_dropped_when_components_owned() -> None:
    rows = [
        {"name": "Alone in the Dark: The Trilogy 1+2+3", "gog_id": 1207658923},
        {"name": "Alone in the Dark 1", "gog_id": 1207660923},
        {"name": "Alone in the Dark 2", "gog_id": 1207660963},
        {"name": "Alone in the Dark 3", "gog_id": 1207660973},
    ]
    out = apply_gog_name_filters(rows)
    names = {r["name"] for r in out}
    assert "Alone in the Dark: The Trilogy 1+2+3" not in names
    assert names == {
        "Alone in the Dark 1",
        "Alone in the Dark 2",
        "Alone in the Dark 3",
    }


def test_sequel_subtitles_not_grouped_by_franchise_prefix() -> None:
    """Tomb Raider sequels must not collapse via edition-variant family key."""
    rows = [
        {
            "name": "Tomb Raider: Anniversary",
            "gog_id": 1,
            "header_image": "https://images.gog.com/a.jpg",
            "genres": ["Action"],
        },
        {
            "name": "Tomb Raider: Legend",
            "gog_id": 2,
            "header_image": None,
            "genres": [],
        },
    ]
    out = collapse_metadata_barren_dupes(rows)
    assert len(out) == 2


def test_all_populated_same_name_both_kept() -> None:
    rows = [
        {
            "name": "Mafia II: Definitive Edition",
            "gog_id": 1,
            "header_image": "https://images.gog.com/a.jpg",
            "genres": ["Adventure"],
        },
        {
            "name": "Mafia II: Definitive Edition",
            "gog_id": 2,
            "header_image": "https://images.gog.com/b.jpg",
            "genres": ["Shooter"],
        },
    ]
    out = collapse_metadata_barren_dupes(rows)
    assert len(out) == 2
