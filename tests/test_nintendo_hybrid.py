"""Tests for Nintendo VGC + transaction hybrid merge."""

from __future__ import annotations

from fetchers.nintendo_hybrid import (
    find_existing_row,
    index_existing_rows,
    merge_vgc_with_transactions,
)


def test_merge_vgc_with_transactions_joins_by_title() -> None:
    vgc = [
        {
            "application_id": "0100abc",
            "vgc_id": "vgc-1",
            "name": "Zelda Tears",
            "platform": "Nintendo Switch",
            "icon_url": "https://img.test/icon.png",
            "is_dlc": False,
        }
    ]
    tx = [
        {
            "name": "Zelda Tears",
            "id": "tx-99",
            "nintendo_id": "tx-99",
            "purchase_date": "2024-01-01",
            "device_type": "HAC",
            "tags": [],
        }
    ]
    merged = merge_vgc_with_transactions(vgc, tx)
    assert len(merged) == 1
    row = merged[0]
    assert row["id"] == "0100abc"
    assert row["application_id"] == "0100abc"
    assert row["nintendo_id"] == "tx-99"
    assert row["purchase_date"] == "2024-01-01"
    assert row["ownership_source"] == "both"
    assert row["icon_url"] == "https://img.test/icon.png"
    assert row["nintendo_platform"] == "Nintendo Switch"


def test_merge_vgc_with_transactions_adds_vgc_only_entitlements() -> None:
    vgc = [
        {
            "application_id": "0100old",
            "vgc_id": "vgc-old",
            "name": "Legacy Cartridge Port",
            "platform": "Nintendo Switch",
            "is_dlc": False,
        }
    ]
    tx = [
        {
            "name": "Recent Buy",
            "id": "tx-1",
            "nintendo_id": "tx-1",
            "purchase_date": "2025-06-01",
            "tags": [],
        }
    ]
    merged = merge_vgc_with_transactions(vgc, tx)
    assert len(merged) == 2
    by_id = {row["id"]: row for row in merged}
    assert by_id["tx-1"]["ownership_source"] == "transaction"
    assert by_id["0100old"]["ownership_source"] == "vgc"
    assert by_id["0100old"]["purchase_date"] is None


def test_find_existing_row_matches_application_id_after_id_migration() -> None:
    existing = {
        "tx-old": {
            "id": "tx-old",
            "nintendo_id": "tx-old",
            "name": "Shared Game",
            "hltb_main_hours": 12,
        }
    }
    by_title, by_app_id, by_nintendo_id = index_existing_rows(existing)
    cached = find_existing_row(
        {
            "id": "0100abc",
            "application_id": "0100abc",
            "nintendo_id": "tx-old",
            "name": "Shared Game",
        },
        existing=existing,
        by_title=by_title,
        by_app_id=by_app_id,
        by_nintendo_id=by_nintendo_id,
    )
    assert cached is not None
    assert cached["hltb_main_hours"] == 12
