import json
from pathlib import Path

from shared.library_noise import (
    edition_base_key,
    edition_title_join_key,
    should_auto_hide_by_title,
    should_auto_hide_gog_title,
    should_auto_hide_nintendo_title,
    should_auto_hide_psn_title,
)

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "library_noise.json"


def test_library_noise_parity_vectors():
    vectors = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    for row in vectors:
        title = row["title"]
        if "should_auto_hide" in row:
            assert should_auto_hide_by_title(title) is row["should_auto_hide"], title
        if "should_auto_hide_psn" in row:
            assert should_auto_hide_psn_title(title) is row["should_auto_hide_psn"], title
        if "should_auto_hide_gog" in row:
            assert should_auto_hide_gog_title(title) is row["should_auto_hide_gog"], title
        if "should_auto_hide_nintendo" in row:
            assert should_auto_hide_nintendo_title(title) is row["should_auto_hide_nintendo"], title
        if row.get("edition_base_key"):
            assert edition_base_key(title) == row["edition_base_key"], title
        if row.get("edition_title_join_key"):
            assert edition_title_join_key(title) == row["edition_title_join_key"], title
