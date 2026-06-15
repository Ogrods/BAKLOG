"""Tests for itch local/api union-merge in fetch_itch.py."""

from __future__ import annotations

import pytest

import fetchers.fetch_itch as fi


def _local_row(itch_id: int, *, name: str = "App Game") -> dict:
    return {
        "store": "itch",
        "id": itch_id,
        "itch_id": itch_id,
        "name": name,
        "source": "local",
    }


def _api_row(itch_id: int, *, name: str = "App Game") -> dict:
    return {
        "store": "itch",
        "id": itch_id,
        "itch_id": itch_id,
        "name": name,
        "source": "api",
    }


class TestMergeItchSources:
    def test_same_id_prefers_local(self) -> None:
        out = fi.merge_itch_sources(
            [_api_row(7)],
            [_local_row(7)],
            "api",
        )
        assert len(out) == 1
        assert out[0]["source"] == "local"

    def test_local_winner_keeps_api_enrichment(self) -> None:
        api = _api_row(42, name="Rated Game")
        api.update(
            {
                "steam_review_percent": 88,
                "steam_review_count": 1200,
                "coop_online": True,
                "hltb_main_hours": 5.0,
            }
        )
        local = _local_row(42, name="Rated Game")
        out = fi.merge_itch_sources([local], [api], "local")
        assert len(out) == 1
        row = out[0]
        assert row["source"] == "local"
        assert row["steam_review_percent"] == 88
        assert row["steam_review_count"] == 1200
        assert row["coop_online"] is True
        assert row["hltb_main_hours"] == 5.0


class TestResolveSource:
    def test_auto_prefers_local(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(fi, "is_local_provider_disabled", lambda _p: False)
        monkeypatch.setattr(fi, "_butler_db_ready", lambda _p: True)
        monkeypatch.setattr(fi, "_api_creds_ready", lambda: True)
        assert fi.resolve_source("auto", None) == "local"

    def test_auto_local_without_api_creds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(fi, "is_local_provider_disabled", lambda _p: False)
        monkeypatch.setattr(fi, "_butler_db_ready", lambda _p: True)
        monkeypatch.setattr(fi, "_api_creds_ready", lambda: False)
        assert fi.resolve_source("auto", None) == "local"

    def test_auto_falls_back_to_api(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(fi, "_butler_db_ready", lambda _p: False)
        monkeypatch.setattr(fi, "_api_creds_ready", lambda: True)
        assert fi.resolve_source("auto", None) == "api"
