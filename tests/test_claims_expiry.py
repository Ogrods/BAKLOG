"""Undated-claim expiry rule shared by build, admin preview and digest."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from shared.claims_expiry import (
    approve_end_date,
    effective_ends_at,
    is_expired,
    is_trusted_live_listing,
    needs_approve_end_date,
    parse_dt,
)

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "claims_expiry.json").read_text(encoding="utf-8")
)
NOW = parse_dt(FIXTURE["now"])


@pytest.mark.parametrize("case", FIXTURE["cases"], ids=lambda c: c["name"])
def test_expiry_parity_vectors(case):
    item = case["item"]
    assert is_trusted_live_listing(item, NOW) is case["trusted"]
    assert is_expired(item, NOW) is case["expired"]
    assert needs_approve_end_date(item, NOW) is case["needs_approve_end_date"]


def test_effective_ends_at_without_now_ignores_live_listing():
    item = {"source": "gamerpower", "first_seen": "2026-09-07T00:00:00+00:00",
            "last_seen": "2026-10-13T04:50:00+00:00"}
    assert effective_ends_at(item) == "2026-09-21T00:00:00Z"
    assert effective_ends_at(item, NOW) is None


def test_approve_end_date_is_14_days_out():
    assert approve_end_date(datetime(2026, 10, 13, 5, 0, 30, 999, tzinfo=UTC)) == (
        "2026-10-27T05:00:30Z"
    )
