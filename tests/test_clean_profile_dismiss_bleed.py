"""Unit tests for scripts/clean_profile_dismiss_bleed.py bleed detection."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.clean_profile_dismiss_bleed import _bleed_ids, _load_personal


def test_bleed_ids_finds_matching_timestamps(tmp_path: Path) -> None:
    default_maps = {
        "__dismissedClaims": {"claim-a": 1000, "claim-b": 2000},
        "__dismissedClaimKeys": {"key-a": 1000},
    }
    promo_maps = {
        "__dismissedClaims": {"claim-a": 1000, "claim-c": 3000},
        "__dismissedClaimKeys": {"key-a": 1000, "key-x": 4000},
    }
    removed = _bleed_ids(default_maps, promo_maps)
    assert removed["__dismissedClaims"] == ["claim-a"]
    assert removed["__dismissedClaimKeys"] == ["key-a"]


def test_bleed_ids_ignores_different_timestamps(tmp_path: Path) -> None:
    default_maps = {"__dismissedClaims": {"claim-a": 1000}}
    promo_maps = {"__dismissedClaims": {"claim-a": 9999}}
    assert _bleed_ids(default_maps, promo_maps) == {}


def test_load_personal_wraps_bare_dict(tmp_path: Path) -> None:
    path = tmp_path / "personal.json"
    path.write_text(json.dumps({"__dismissedClaims": {"x": 1}}), encoding="utf-8")
    doc = _load_personal(path)
    assert doc["personal"]["__dismissedClaims"] == {"x": 1}
