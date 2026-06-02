"""Tests for Steam review enrichment helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "enrich_steam_reviews",
    _ROOT / "enrich_steam_reviews.py",
)
_mod = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_mod)

_close_enough_title = _mod._close_enough_title
normalize = _mod.normalize


@pytest.mark.parametrize(
    ("target", "candidate", "expected"),
    [
        ("death stranding", "death stranding 2 on beach", False),
        ("death stranding", "death stranding", True),
        ("death stranding 2", "death stranding 2 on beach", True),
        ("control", "control ultimate edition", True),
        ("age of wonders", "age of wonders 4", False),
    ],
)
def test_close_enough_title_sequel_guard(target: str, candidate: str, expected: bool) -> None:
    assert _close_enough_title(normalize(target), normalize(candidate)) is expected
