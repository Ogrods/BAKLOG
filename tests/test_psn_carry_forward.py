"""PSN carry-forward pruning when trophy/entitlement ids churn."""

from __future__ import annotations

from fetchers._base import STALE_FIELD
from fetchers.fetch_psn import apply_psn_carry_forward, prune_stale_psn_duplicates


def test_apply_psn_carry_forward_prunes_stale_id_churn_sibling() -> None:
    fresh = [
        {
            "id": "NPWR42480_00",
            "name": "Warhammer 40,000: Darktide",
            "psn_platforms": ["PS5"],
        }
    ]
    existing = {
        "PPSA21255_00": {
            "id": "PPSA21255_00",
            "name": "Warhammer 40,000: Darktide",
            "psn_platforms": ["PS5"],
            STALE_FIELD: True,
        }
    }
    out = apply_psn_carry_forward(fresh, existing, no_carry=False)
    ids = {r["id"] for r in out}
    assert ids == {"NPWR42480_00"}
    assert STALE_FIELD not in out[0]


def test_prune_stale_psn_duplicates_repair() -> None:
    games = [
        {"id": "NPWR39259_00", "name": "SONIC X SHADOW GENERATIONS"},
        {
            "id": "PPSA17597_00",
            "name": "SONIC X SHADOW GENERATIONS",
            STALE_FIELD: True,
        },
        {"id": "PPSA28176_00", "name": "Battlefield 6", STALE_FIELD: True},
    ]
    repaired, dropped = prune_stale_psn_duplicates(games)
    assert dropped == 1
    assert len(repaired) == 2
    assert {g["id"] for g in repaired} == {"NPWR39259_00", "PPSA28176_00"}
