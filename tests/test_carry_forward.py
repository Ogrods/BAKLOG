"""Unit tests for library fetcher carry-forward helpers."""

from __future__ import annotations

from fetchers._base import (
    LAST_SEEN_FIELD,
    STALE_FIELD,
    STALE_SINCE_FIELD,
    apply_carry_forward,
    carry_forward_missing,
    refuse_drift_result,
    row_key_by_appid,
    row_key_by_id,
)


def test_carry_forward_missing_adds_stale_row() -> None:
    fresh = [{"id": "1", "name": "Alpha"}]
    existing = [
        {"id": "1", "name": "Alpha"},
        {"id": "2", "name": "Beta", "hltb_main_hours": 10},
    ]
    out = carry_forward_missing(
        fresh,
        existing,
        key_fn=row_key_by_id,
        now_iso="2026-06-08T12:00:00+00:00",
    )
    assert len(out) == 2
    by_id = {r["id"]: r for r in out}
    assert by_id["1"][LAST_SEEN_FIELD] == "2026-06-08T12:00:00+00:00"
    assert STALE_FIELD not in by_id["1"]
    assert by_id["2"][STALE_FIELD] is True
    assert by_id["2"][STALE_SINCE_FIELD] == "2026-06-08T12:00:00+00:00"
    assert by_id["2"]["hltb_main_hours"] == 10


def test_carry_forward_missing_clears_stale_when_row_returns() -> None:
    fresh = [{"id": "2", "name": "Beta"}]
    existing = [
        {
            "id": "2",
            "name": "Beta",
            STALE_FIELD: True,
            STALE_SINCE_FIELD: "2026-06-01T00:00:00+00:00",
            LAST_SEEN_FIELD: "2026-06-01T00:00:00+00:00",
        }
    ]
    out = carry_forward_missing(
        fresh,
        existing,
        key_fn=row_key_by_id,
        now_iso="2026-06-08T12:00:00+00:00",
    )
    assert len(out) == 1
    row = out[0]
    assert row[LAST_SEEN_FIELD] == "2026-06-08T12:00:00+00:00"
    assert STALE_FIELD not in row
    assert STALE_SINCE_FIELD not in row


def test_carry_forward_preserves_original_stale_since() -> None:
    fresh: list[dict] = []
    existing = [
        {
            "id": "9",
            "name": "Old",
            STALE_SINCE_FIELD: "2026-01-01T00:00:00+00:00",
        }
    ]
    out = carry_forward_missing(
        fresh,
        existing,
        key_fn=row_key_by_id,
        now_iso="2026-06-08T12:00:00+00:00",
    )
    assert out[0][STALE_SINCE_FIELD] == "2026-01-01T00:00:00+00:00"


def test_apply_carry_forward_no_carry_skips_union() -> None:
    fresh = [{"id": "1", "name": "Only"}]
    existing = {"2": {"id": "2", "name": "Gone"}}
    out = apply_carry_forward(fresh, existing, key_fn=row_key_by_id, no_carry=True)
    assert out == fresh


def test_row_key_by_appid_prefers_appid() -> None:
    assert row_key_by_appid({"appid": 570, "id": "steam-570"}) == "570"
    assert row_key_by_appid({"id": "manual-1"}) == "manual-1"


def test_multi_source_match_key_dedup_not_double_counted() -> None:
    def match_key(row: dict) -> str:
        gid = row.get("gog_id") or row.get("id")
        return f"gog_id:{gid}"

    fresh = [{"id": 10, "gog_id": 10, "name": "Fresh", "source": "web"}]
    existing = [
        {"id": 10, "gog_id": 10, "name": "Fresh", "source": "local", "hltb_main_hours": 5},
        {"id": 99, "gog_id": 99, "name": "Carried", "source": "local"},
    ]
    out = carry_forward_missing(fresh, existing, key_fn=match_key, now_iso="2026-06-08T12:00:00+00:00")
    assert len(out) == 2
    keys = {match_key(r) for r in out}
    assert keys == {"gog_id:10", "gog_id:99"}
    fresh_row = next(r for r in out if r["id"] == 10)
    assert fresh_row["source"] == "web"
    assert STALE_FIELD not in fresh_row


def test_drift_guard_runs_before_carry_forward_semantics() -> None:
    """Drift on fresh-only count can refuse while carry-forward would inflate total."""
    fresh_count = 1
    prev_count = 10
    # Simulate refuse_drift on fresh slice only — under 50% floor => exit 3
    floor = max(1, int(prev_count * 0.5))
    assert fresh_count < floor
    # carry-forward would restore to 10; drift must run on fresh first in fetchers
    carried = carry_forward_missing(
        [{"id": "1", "name": "A"}],
        [{"id": str(i), "name": f"G{i}"} for i in range(2, 11)],
        key_fn=row_key_by_id,
    )
    assert len(carried) == 10
    # Drift helper itself compares new_count to on-disk prev — independent of carry
    assert refuse_drift_result(fresh_count, label="t", allow_drift=False, output_path=None) is None
