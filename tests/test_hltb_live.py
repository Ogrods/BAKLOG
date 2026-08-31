"""Pre-release smoke: live HowLongToBeat search must return results.

Run before tagging (also in release.yml and test-all.ps1 -Full):

    python -m pytest -q -m release_smoke
"""

from __future__ import annotations

import pytest

from clients.hltb_client import HltbClient


@pytest.mark.release_smoke
def test_hltb_search_returns_portal_2() -> None:
    """howlongtobeatpy must track HLTB site changes; empty search means bump the lib."""
    hit = HltbClient().lookup("Portal 2")
    assert hit is not None, (
        "HLTB search returned no results for Portal 2 - "
        "bump howlongtobeatpy (site API likely changed again)"
    )
    assert hit.get("hltb_main_hours") is not None
    assert float(hit["hltb_main_hours"]) > 0
