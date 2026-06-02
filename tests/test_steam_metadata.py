"""Unit tests for steam_metadata helpers (coop classification + enrichment merge)."""

from __future__ import annotations

import pytest

from steam_metadata import (
    ALWAYS_WRITE_FIELDS,
    FILL_IF_MISSING_FIELDS,
    apply_enrichment_to_row,
    coop_flags_from_categories,
    enrichment_from_appdetails,
)


def _cats(*names: str) -> list[dict]:
    return [{"description": n} for n in names]


class TestCoopFlags:
    def test_empty_or_none(self) -> None:
        assert coop_flags_from_categories(None) == (False, False)
        assert coop_flags_from_categories([]) == (False, False)

    def test_online_coop_alone(self) -> None:
        assert coop_flags_from_categories(_cats("Single-player", "Online Co-op")) == (True, False)

    def test_local_coop_alone(self) -> None:
        cats = _cats("Multi-player", "Shared/Split Screen Co-op")
        assert coop_flags_from_categories(cats) == (False, True)

    def test_both_kinds(self) -> None:
        cats = _cats("Online Co-op", "Shared/Split Screen Co-op")
        assert coop_flags_from_categories(cats) == (True, True)

    def test_lan_counts_as_online(self) -> None:
        # LAN is co-op across machines — fold into online for filter purposes.
        assert coop_flags_from_categories(_cats("LAN Co-op")) == (True, False)

    def test_bare_coop_is_unknown(self) -> None:
        # A bare "Co-op" (no flavor) shouldn't claim either kind.
        assert coop_flags_from_categories(_cats("Co-op")) == (False, False)

    def test_case_insensitive(self) -> None:
        assert coop_flags_from_categories(_cats("online co-op")) == (True, False)
        assert coop_flags_from_categories(_cats("ONLINE CO-OP")) == (True, False)


class TestEnrichmentFromAppdetails:
    def test_none_payload_returns_empty_shape(self) -> None:
        result = enrichment_from_appdetails(None)
        assert result == {
            "coop_online": False,
            "coop_local": False,
            "genres": [],
            "release_date": None,
        }

    def test_full_payload(self) -> None:
        details = {
            "categories": _cats("Online Co-op", "Steam Achievements"),
            "genres": [{"description": "Action"}, {"description": "RPG"}],
            "release_date": {"date": "Nov 8, 2019"},
            # Unsupported fields on the payload must be silently ignored —
            # the enricher promises not to write anything beyond the four
            # documented keys.
            "metacritic": {"score": 82},
            "controller_support": "full",
            "achievements": {"total": 45},
        }
        result = enrichment_from_appdetails(details)
        assert result == {
            "coop_online": True,
            "coop_local": False,
            "genres": ["Action", "RPG"],
            "release_date": "Nov 8, 2019",
        }

    def test_genres_skips_missing_descriptions(self) -> None:
        details = {"genres": [{"description": "Action"}, {}, {"description": "  "}]}
        # Empty/blank descriptions get filtered; non-string-coerce keeps trim.
        result = enrichment_from_appdetails(details)
        assert "Action" in result["genres"]
        assert all(g.strip() for g in result["genres"])

    def test_blank_release_date_becomes_none(self) -> None:
        assert enrichment_from_appdetails({"release_date": {"date": "   "}})[
            "release_date"
        ] is None
        assert enrichment_from_appdetails({"release_date": {}})["release_date"] is None


class TestApplyEnrichmentToRow:
    def test_always_writes_coop_flags(self) -> None:
        row = {"name": "X"}
        enrichment = {
            "coop_online": True,
            "coop_local": False,
            "genres": [],
            "release_date": None,
            "metacritic_score": None,
            "controller_support": None,
            "achievements_total": None,
        }
        apply_enrichment_to_row(row, enrichment)
        assert row["coop_online"] is True
        assert row["coop_local"] is False

    def test_does_not_clobber_existing_genres(self) -> None:
        row = {"name": "X", "genres": ["Strategy"]}
        enrichment = {"coop_online": False, "coop_local": False, "genres": ["Action"]}
        apply_enrichment_to_row(row, enrichment)
        assert row["genres"] == ["Strategy"]

    def test_fills_missing_genres(self) -> None:
        row = {"name": "X"}
        enrichment = {"coop_online": False, "coop_local": False, "genres": ["RPG"]}
        apply_enrichment_to_row(row, enrichment)
        assert row["genres"] == ["RPG"]

    def test_fills_empty_genres_list(self) -> None:
        row = {"name": "X", "genres": []}
        enrichment = {"coop_online": False, "coop_local": False, "genres": ["RPG"]}
        apply_enrichment_to_row(row, enrichment)
        assert row["genres"] == ["RPG"]

    def test_does_not_clobber_existing_release_date(self) -> None:
        row = {"name": "X", "release_date": "2020-01-01"}
        enrichment = {
            "coop_online": False,
            "coop_local": False,
            "release_date": "Apr 1, 2021",
        }
        apply_enrichment_to_row(row, enrichment)
        assert row["release_date"] == "2020-01-01"

    def test_always_write_fields_set_means_correct_partitioning(self) -> None:
        # If anyone moves a field between the two sets they should be forced to
        # update tests above too. Locking the partition keeps that honest.
        assert ALWAYS_WRITE_FIELDS == frozenset({"coop_online", "coop_local"})
        assert FILL_IF_MISSING_FIELDS == frozenset({"genres", "release_date"})
        assert not (ALWAYS_WRITE_FIELDS & FILL_IF_MISSING_FIELDS)


@pytest.mark.parametrize(
    ("appdetails", "expected_online", "expected_local"),
    [
        ({}, False, False),
        ({"categories": [{"description": "Single-player"}]}, False, False),
        ({"categories": [{"description": "Online Co-op"}]}, True, False),
        ({"categories": [{"description": "Shared/Split Screen Co-op"}]}, False, True),
        (
            {
                "categories": [
                    {"description": "Online Co-op"},
                    {"description": "Shared/Split Screen Co-op"},
                ]
            },
            True,
            True,
        ),
    ],
)
def test_appdetails_to_coop_end_to_end(
    appdetails: dict, expected_online: bool, expected_local: bool
) -> None:
    result = enrichment_from_appdetails(appdetails)
    assert result["coop_online"] is expected_online
    assert result["coop_local"] is expected_local
