"""Offline integration test for enrich_steam_tags.

Creates a temp workspace with fake non-Steam game JSON + a fake appid mapping,
monkey-patches SteamClient so no network calls happen, then runs the script's
main(). Verifies coop_online/coop_local get written, missing genres get
filled, and existing genres are not overwritten.
"""

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
    # auth.manager imports get_active_profile_id at module load — patch both bindings.
    monkeypatch.setattr("auth.manager.get_active_profile_id", lambda: DEFAULT_PROFILE_ID)
    (tmp_path / "cache").mkdir()
    # Mapping built by enrich_steam_reviews.py — only "gog:1" has a match.
    (tmp_path / "cache" / "steam_review_map.json").write_text(
        json.dumps(
            {
                "gog:1": 4242,         # mapped → enrichment runs
                "gog:2": 0,            # known miss → skipped
                # gog:3 has no entry  → skipped (unmapped)
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "games_gog.json").write_text(
        json.dumps(
            {
                "fetched_at": "2026-01-01T00:00:00Z",
                "games": [
                    # Row 1: no genres, no coop fields → should get both filled.
                    {
                        "id": "1",
                        "name": "Coop Title",
                        "playtime_minutes": 0,
                    },
                    # Row 2: existing genres → must NOT be overwritten.
                    {
                        "id": "2",
                        "name": "No Match",
                        "playtime_minutes": 0,
                        "genres": ["GOG-classic"],
                    },
                    # Row 3: not in mapping at all → completely untouched.
                    {
                        "id": "3",
                        "name": "Unmapped",
                        "playtime_minutes": 0,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    # Required-by-enricher env (resolve_env reads from os.environ).
    monkeypatch.setenv("STEAM_API_KEY", "test_key")
    monkeypatch.setenv("STEAM_ID", "76561197960287930")
    return tmp_path


def test_enricher_writes_coop_and_fills_missing_genres(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Force a fresh import so the script picks up the patched cwd / env.
    for mod in ("enrichers.enrich_steam_tags", "clients.steam_client"):
        sys.modules.pop(mod, None)
    import enrichers.enrich_steam_tags as enrich_steam_tags
    from clients.steam_client import SteamClient

    canned = {
        4242: {
            "success": True,
            "data": {
                "type": "game",
                "name": "Coop Title",
                "categories": [
                    {"description": "Single-player"},
                    {"description": "Online Co-op"},
                ],
                "genres": [{"description": "Action"}, {"description": "RPG"}],
                "release_date": {"date": "Mar 15, 2024"},
                # Payload may contain other fields we know about; enricher
                # must not write them onto the row.
                "metacritic": {"score": 88},
                "controller_support": "full",
                "developers": ["Enrich Dev"],
                "publishers": ["Enrich Pub"],
                "achievements": {"total": 30},
            },
        }
    }

    def fake_get_app_details(self, appid: int, refresh: bool = False) -> dict | None:
        return canned.get(appid)

    monkeypatch.setattr(SteamClient, "get_app_details", fake_get_app_details)

    exit_code = enrich_steam_tags.main([])
    assert exit_code == 0

    written = json.loads((workspace / "games_gog.json").read_text(encoding="utf-8"))
    rows = {g["id"]: g for g in written["games"]}

    # Row 1 — mapped to appid 4242, every supported field populated.
    g1 = rows["1"]
    assert g1["coop_online"] is True
    assert g1["coop_local"] is False
    assert g1["genres"] == ["Action", "RPG"]
    assert g1["release_date"] == "Mar 15, 2024"
    assert g1["metacritic_score"] == 88
    assert g1["controller_support"] == "full"
    assert g1["developers"] == ["Enrich Dev"]
    assert g1["publishers"] == ["Enrich Pub"]
    assert g1["early_access"] is False
    assert "achievements_total" not in g1

    # Row 2 — appid match 0 in mapping → no enrichment, existing genres kept.
    g2 = rows["2"]
    assert g2["genres"] == ["GOG-classic"]
    assert "coop_online" not in g2

    # Row 3 — not in mapping at all → completely untouched.
    g3 = rows["3"]
    assert "coop_online" not in g3
    assert "genres" not in g3

    # Run meta cache for the dashboard chip should be written.
    meta = json.loads(
        (workspace / "cache" / "steam_tags_meta.json").read_text(encoding="utf-8")
    )
    assert meta["rows_updated"] >= 1
    assert meta["rows_with_appid"] >= 1
    assert "fetched_at" in meta


def test_enricher_marks_failed_appdetails_as_checked(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """success:false must still write coop false/false so the chip clears."""
    for mod in ("enrichers.enrich_steam_tags", "clients.steam_client"):
        sys.modules.pop(mod, None)
    import enrichers.enrich_steam_tags as enrich_steam_tags
    from clients.steam_client import SteamClient

    def fake_get_app_details(self, appid: int, refresh: bool = False) -> dict | None:
        return {"success": False, "data": None}

    monkeypatch.setattr(SteamClient, "get_app_details", fake_get_app_details)

    exit_code = enrich_steam_tags.main([])
    assert exit_code == 0

    written = json.loads((workspace / "games_gog.json").read_text(encoding="utf-8"))
    rows = {g["id"]: g for g in written["games"]}

    g1 = rows["1"]
    assert g1["coop_online"] is False
    assert g1["coop_local"] is False
    # Failed details must not invent genres / release date.
    assert "genres" not in g1
    assert "release_date" not in g1

    # Unmapped / known-miss rows stay untouched.
    assert "coop_online" not in rows["2"]
    assert "coop_online" not in rows["3"]


def test_enricher_leaves_pending_on_appdetails_exception(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Network errors must not clear the pending chip — retry later."""
    for mod in ("enrichers.enrich_steam_tags", "clients.steam_client"):
        sys.modules.pop(mod, None)
    import enrichers.enrich_steam_tags as enrich_steam_tags
    from clients.steam_client import SteamClient

    def fake_get_app_details(self, appid: int, refresh: bool = False) -> dict | None:
        raise RuntimeError("network down")

    monkeypatch.setattr(SteamClient, "get_app_details", fake_get_app_details)

    exit_code = enrich_steam_tags.main([])
    assert exit_code == 0

    written = json.loads((workspace / "games_gog.json").read_text(encoding="utf-8"))
    rows = {g["id"]: g for g in written["games"]}
    assert "coop_online" not in rows["1"]
    assert "coop_local" not in rows["1"]


def test_enricher_dry_run_does_not_write(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for mod in ("enrichers.enrich_steam_tags", "clients.steam_client"):
        sys.modules.pop(mod, None)
    import enrichers.enrich_steam_tags as enrich_steam_tags
    from clients.steam_client import SteamClient

    def fake_get_app_details(self, appid: int, refresh: bool = False) -> dict | None:
        return {
            "success": True,
            "data": {
                "categories": [{"description": "Online Co-op"}],
                "genres": [{"description": "Action"}],
            },
        }

    monkeypatch.setattr(SteamClient, "get_app_details", fake_get_app_details)
    before = (workspace / "games_gog.json").read_text(encoding="utf-8")

    exit_code = enrich_steam_tags.main(["--dry-run"])
    assert exit_code == 0

    after = (workspace / "games_gog.json").read_text(encoding="utf-8")
    assert before == after, "dry-run must not write back to the JSON file"
    assert not (workspace / "cache" / "steam_tags_meta.json").exists()


def test_enricher_bails_without_mapping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("shared.profile_paths.profile_root", lambda profile_id=None: tmp_path)
    monkeypatch.setenv("STEAM_API_KEY", "test_key")
    monkeypatch.setenv("STEAM_ID", "76561197960287930")
    for mod in ("enrichers.enrich_steam_tags",):
        sys.modules.pop(mod, None)
    import enrichers.enrich_steam_tags as enrich_steam_tags

    exit_code = enrich_steam_tags.main([])
    assert exit_code == 0
