"""Offline tests for enrich_protondb."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from shared.profile_paths import DEFAULT_PROFILE_ID

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("shared.profile_paths.profile_root", lambda profile_id=None: tmp_path)
    monkeypatch.setattr(
        "shared.profile_paths.get_active_profile_id",
        lambda: DEFAULT_PROFILE_ID,
    )
    monkeypatch.setattr("auth.manager.get_active_profile_id", lambda: DEFAULT_PROFILE_ID)
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / "steam_review_map.json").write_text(
        json.dumps({"gog:1": 4242}),
        encoding="utf-8",
    )
    (tmp_path / "games_steam.json").write_text(
        json.dumps(
            {
                "fetched_at": "2026-01-01T00:00:00Z",
                "games": [{"id": 570, "name": "Dota 2", "playtime_minutes": 0}],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "games_gog.json").write_text(
        json.dumps(
            {
                "fetched_at": "2026-01-01T00:00:00Z",
                "games": [
                    {"id": "1", "name": "Mapped GOG", "playtime_minutes": 0},
                    {"id": "2", "name": "Unmapped", "playtime_minutes": 0},
                ],
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


def test_effective_tier_prefers_confirmed_over_pending() -> None:
    from enrich_protondb import effective_tier, summary_to_row_fields

    assert effective_tier({"tier": "pending", "provisionalTier": "gold"}) == "gold"
    fields = summary_to_row_fields(
        {
            "tier": "platinum",
            "confidence": "high",
            "total": 42,
            "score": 0.91,
            "trendingTier": "gold",
        }
    )
    assert fields["protondb_tier"] == "platinum"
    assert fields["protondb_report_count"] == 42


def test_enricher_writes_steam_and_mapped_gog_rows(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []

    def fake_fetch(appid: int):
        calls.append(appid)
        if appid == 570:
            return {
                "tier": "gold",
                "confidence": "strong",
                "total": 10,
                "score": 0.8,
                "trendingTier": "gold",
            }
        if appid == 4242:
            return False
        return None

    for mod in ("enrich_protondb",):
        sys.modules.pop(mod, None)
    import enrich_protondb

    monkeypatch.setattr(enrich_protondb, "fetch_summary", fake_fetch)

    exit_code = enrich_protondb.main([])
    assert exit_code == 0
    assert calls == [570, 4242]

    steam = json.loads((workspace / "games_steam.json").read_text(encoding="utf-8"))
    assert steam["games"][0]["protondb_tier"] == "gold"
    assert steam["games"][0]["protondb_report_count"] == 10

    gog = json.loads((workspace / "games_gog.json").read_text(encoding="utf-8"))
    assert "protondb_tier" not in gog["games"][0]
    assert "protondb_tier" not in gog["games"][1]

    cache = json.loads((workspace / "cache" / "protondb_map.json").read_text(encoding="utf-8"))
    assert cache["570"]["tier"] == "gold"
    assert cache["4242"] is False
