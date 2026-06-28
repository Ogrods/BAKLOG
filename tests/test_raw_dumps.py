"""Tests for shared/raw_dumps.py opt-in gate."""

from __future__ import annotations

import pytest

from shared.raw_dumps import raw_dumps_enabled


@pytest.mark.parametrize(
    "value,expected",
    [
        ("1", True),
        ("true", True),
        ("yes", True),
        ("on", True),
        ("", False),
        ("0", False),
        ("false", False),
    ],
)
def test_raw_dumps_enabled(monkeypatch: pytest.MonkeyPatch, value: str, expected: bool) -> None:
    monkeypatch.setenv("BAKLOG_RAW_DUMPS", value)
    assert raw_dumps_enabled() is expected
