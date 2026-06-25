"""Cross-implementation parity for library noise rules (shared fixture)."""

from __future__ import annotations

import json
from pathlib import Path

from shared.library_noise import edition_base_key, should_auto_hide_by_title

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "library_noise.json"


def test_library_noise_parity_vectors() -> None:
    vectors = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    for row in vectors:
        title = row["title"]
        if "should_auto_hide" in row:
            assert should_auto_hide_by_title(title) is row["should_auto_hide"], title
        if row.get("edition_base_key"):
            assert edition_base_key(title) == row["edition_base_key"], title
