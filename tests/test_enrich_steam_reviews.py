"""Tests for Steam review enrichment helpers."""

from __future__ import annotations

import pytest

from shared.steam_match import close_enough_title, normalize_title


@pytest.mark.parametrize(
    ("target", "candidate", "expected"),
    [
        ("death stranding", "death stranding 2 on beach", False),
        ("death stranding", "death stranding director s cut", False),
        ("death stranding", "death stranding digital artbook", False),
        ("death stranding", "death stranding", True),
        ("death stranding 2", "death stranding 2 on beach", True),
        ("control", "control ultimate edition", True),
        ("age of wonders", "age of wonders 4", False),
    ],
)
def test_close_enough_title_sequel_guard(target: str, candidate: str, expected: bool) -> None:
    assert close_enough_title(normalize_title(target), normalize_title(candidate)) is expected
