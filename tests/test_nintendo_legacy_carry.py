"""Tests for Nintendo legacy carry-forward and drift baseline."""

from __future__ import annotations

import json
from pathlib import Path

from fetchers._base import LAST_SEEN_FIELD, STALE_FIELD, STALE_SINCE_FIELD, row_key_by_id
from fetchers.fetch_nintendo import (
    NINTENDO_LEGACY_FIELD,
    _nintendo_drift_baseline,
    carry_forward_nintendo_legacy,
    load_nintendo_dropped_ids,
    maybe_repair_nintendo_catalog_on_disk,
    refuse_nintendo_source_drift,
    repair_nintendo_stale_catalog,
)


def test_carry_forward_nintendo_legacy_tags_legacy_not_stale() -> None:
    fresh = [{"id": "1", "name": "Alpha"}]
    existing = [
        {"id": "1", "name": "Alpha"},
        {
            "id": "2",
            "name": "Beta",
            STALE_FIELD: True,
            STALE_SINCE_FIELD: "2026-01-01T00:00:00+00:00",
            "hltb_main_hours": 10,
        },
    ]
    out = carry_forward_nintendo_legacy(
        fresh,
        existing,
        dropped_ids=set(),
        key_fn=row_key_by_id,
        now_iso="2026-06-25T12:00:00+00:00",
    )
    assert len(out) == 2
    by_id = {r["id"]: r for r in out}
    assert by_id["1"][LAST_SEEN_FIELD] == "2026-06-25T12:00:00+00:00"
    assert NINTENDO_LEGACY_FIELD not in by_id["1"]
    assert STALE_FIELD not in by_id["1"]
    assert by_id["2"][NINTENDO_LEGACY_FIELD] is True
    assert STALE_FIELD not in by_id["2"]
    assert STALE_SINCE_FIELD not in by_id["2"]
    assert by_id["2"]["hltb_main_hours"] == 10


def test_carry_forward_nintendo_legacy_skips_dropped_ids() -> None:
    fresh = [{"id": "1", "name": "Alpha"}]
    existing = [
        {"id": "1", "name": "Alpha"},
        {"id": "2", "name": "Dropped"},
        {"id": "3", "name": "Legacy"},
    ]
    out = carry_forward_nintendo_legacy(
        fresh,
        existing,
        dropped_ids={"2"},
        key_fn=row_key_by_id,
        now_iso="2026-06-25T12:00:00+00:00",
    )
    ids = {r["id"] for r in out}
    assert ids == {"1", "3"}
    legacy = next(r for r in out if r["id"] == "3")
    assert legacy[NINTENDO_LEGACY_FIELD] is True


def test_carry_forward_nintendo_legacy_clears_legacy_when_row_returns() -> None:
    fresh = [{"id": "2", "name": "Beta", NINTENDO_LEGACY_FIELD: True}]
    existing = [{"id": "2", "name": "Beta", NINTENDO_LEGACY_FIELD: True}]
    out = carry_forward_nintendo_legacy(
        fresh,
        existing,
        dropped_ids=set(),
        key_fn=row_key_by_id,
        now_iso="2026-06-25T12:00:00+00:00",
    )
    assert len(out) == 1
    assert NINTENDO_LEGACY_FIELD not in out[0]


def test_nintendo_drift_baseline_prefers_fresh_count(tmp_path: Path, monkeypatch) -> None:
    catalog = tmp_path / "games_nintendo.json"
    catalog.write_text(
        json.dumps(
            {
                "game_count": 120,
                "fresh_count": 45,
                "games": [{"id": "1"}, {"id": "2", "nintendo_legacy": True}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("fetchers.fetch_nintendo.catalog_file", lambda _p: catalog)
    assert _nintendo_drift_baseline(Path("games_nintendo.json")) == 45


def test_nintendo_drift_baseline_falls_back_to_non_legacy_rows(tmp_path: Path, monkeypatch) -> None:
    catalog = tmp_path / "games_nintendo.json"
    catalog.write_text(
        json.dumps(
            {
                "game_count": 5,
                "games": [
                    {"id": "1"},
                    {"id": "2", "nintendo_legacy": True},
                    {"id": "3", "stale": True},
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("fetchers.fetch_nintendo.catalog_file", lambda _p: catalog)
    assert _nintendo_drift_baseline(Path("games_nintendo.json")) == 1


def test_refuse_nintendo_drift_uses_fresh_baseline_not_total(
    tmp_path: Path, monkeypatch
) -> None:
    catalog = tmp_path / "games_nintendo.json"
    catalog.write_text(
        json.dumps({"game_count": 120, "fresh_count": 45, "games": []}),
        encoding="utf-8",
    )
    monkeypatch.setattr("fetchers.fetch_nintendo.catalog_file", lambda _p: catalog)
    rows = [{"id": str(i)} for i in range(40)]
    assert (
        refuse_nintendo_source_drift(
            rows,
            label="Nintendo library rows",
            allow_drift=False,
            output_path=Path("games_nintendo.json"),
        )
        is None
    )
    small = [{"id": str(i)} for i in range(20)]
    assert (
        refuse_nintendo_source_drift(
            small,
            label="Nintendo library rows",
            allow_drift=False,
            output_path=Path("games_nintendo.json"),
        )
        == 3
    )


def test_load_nintendo_dropped_ids_reads_personal(tmp_path: Path, monkeypatch) -> None:
    personal = tmp_path / "data" / "personal.json"
    personal.parent.mkdir(parents=True)
    personal.write_text(
        json.dumps(
            {
                "personal": {"__nintendo_dropped_ids_v1": ["tx-1", "tx-2"]},
                "prefs": {},
                "manual": [],
                "libraryFirstSeen": {},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("fetchers.fetch_nintendo.personal_path", lambda **_: personal)
    assert load_nintendo_dropped_ids() == {"tx-1", "tx-2"}


def test_dropped_ids_excluded_from_fresh_slice() -> None:
    """User-removed titles must not reappear when still in the 2yr API window."""
    fresh = [
        {"id": "1", "name": "Alpha"},
        {"id": "2", "name": "Dropped but still on API"},
    ]
    out = carry_forward_nintendo_legacy(
        fresh,
        [],
        dropped_ids={"2"},
        key_fn=row_key_by_id,
        now_iso="2026-06-25T12:00:00+00:00",
    )
    out = [row for row in out if row_key_by_id(row) not in {"2"}]
    assert {r["id"] for r in out} == {"1"}


def test_carry_forward_nintendo_legacy_skips_title_match_when_id_churns() -> None:
    fresh = [{"id": "new-tx", "name": "Mario Kart 8 Deluxe"}]
    existing = [
        {
            "id": "old-tx",
            "name": "Mario Kart 8 Deluxe",
            STALE_FIELD: True,
            "hltb_main_hours": 12,
        },
    ]
    out = carry_forward_nintendo_legacy(
        fresh,
        existing,
        dropped_ids=set(),
        key_fn=row_key_by_id,
        now_iso="2026-06-25T12:00:00+00:00",
    )
    assert len(out) == 1
    assert out[0]["id"] == "new-tx"
    assert out[0].get("hltb_main_hours") is None


def test_repair_nintendo_stale_catalog_promotes_legacy() -> None:
    games = [
        {"id": "1", "name": "Fresh"},
        {
            "id": "2",
            "name": "Old",
            STALE_FIELD: True,
            STALE_SINCE_FIELD: "2026-01-01T00:00:00+00:00",
        },
    ]
    out, repaired = repair_nintendo_stale_catalog(games)
    assert repaired == 1
    assert out[0].get(STALE_FIELD) is None
    assert out[1][NINTENDO_LEGACY_FIELD] is True
    assert STALE_FIELD not in out[1]
    assert STALE_SINCE_FIELD not in out[1]


def test_repair_nintendo_stale_catalog_skips_dropped_ids() -> None:
    games = [{"id": "gone", "name": "Gone", STALE_FIELD: True}]
    out, repaired = repair_nintendo_stale_catalog(games, dropped_ids={"gone"})
    assert repaired == 0
    assert out[0][STALE_FIELD] is True


def test_maybe_repair_nintendo_catalog_on_disk_writes(tmp_path: Path, monkeypatch) -> None:
    catalog = tmp_path / "games_nintendo.json"
    catalog.write_text(
        json.dumps(
            {
                "games": [
                    {"id": "1", "name": "A"},
                    {"id": "2", "name": "B", STALE_FIELD: True},
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "fetchers.fetch_nintendo.catalog_file",
        lambda _rel: catalog,
    )
    monkeypatch.setattr(
        "fetchers.fetch_nintendo.write_catalog_text",
        lambda _rel, text: catalog.write_text(text, encoding="utf-8"),
    )
    assert maybe_repair_nintendo_catalog_on_disk() == 1
    payload = json.loads(catalog.read_text(encoding="utf-8"))
    legacy = next(g for g in payload["games"] if g["id"] == "2")
    assert legacy[NINTENDO_LEGACY_FIELD] is True
    assert STALE_FIELD not in legacy
