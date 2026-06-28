import os
from pathlib import Path

import fetchers.fetch_gog as fg
from auth.manager import _local_data_present


def _local_row(gog_id, *, name="Galaxy Game"):
    return {"store": "gog", "id": gog_id, "gog_id": gog_id, "name": name, "source": "local"}


def _web_row(gog_id, *, name="Galaxy Game"):
    return {"store": "gog", "id": gog_id, "gog_id": gog_id, "name": name, "source": "web"}


class TestMergeGogSources:
    def test_union_keeps_both_slices(self):
        out = fg.merge_gog_sources([_web_row(2, name="Web Only")], [_local_row(1, name="Local Only")], "web")
        assert {g["name"] for g in out} == {"Web Only", "Local Only"}

    def test_same_id_prefers_local(self):
        out = fg.merge_gog_sources([_web_row(100, name="Same")], [_local_row(100, name="Same")], "web")
        assert len(out) == 1
        assert out[0]["source"] == "local"

    def test_duplicate_gog_id_collapses_to_one_row(self):
        out = fg.merge_gog_sources([_web_row(42, name="Dup")], [_local_row(42, name="Dup Local")], "local")
        assert len(out) == 1
        assert out[0]["gog_id"] == 42

    def test_same_name_different_id_keeps_both(self):
        out = fg.merge_gog_sources([_web_row(10, name="Shared Title")], [_local_row(11, name="Shared Title")], "web")
        assert len(out) == 2

    def test_local_winner_keeps_web_enrichment(self):
        web = _web_row(200, name="Enriched")
        web.update({"steam_review_percent": 92, "coop_local": True, "hltb_main_hours": 12.0})
        local = _local_row(200, name="Enriched")
        out = fg.merge_gog_sources([local], [web], "local")
        assert len(out) == 1
        row = out[0]
        assert row["source"] == "local"
        assert row["steam_review_percent"] == 92
        assert row["coop_local"] is True
        assert row["hltb_main_hours"] == 12.0


class TestResolveSource:
    def test_auto_prefers_local(self, monkeypatch):
        monkeypatch.setattr(fg, "is_local_provider_disabled", lambda _p: False)
        monkeypatch.setattr(fg, "_galaxy_db_ready", lambda _p: True)
        monkeypatch.setattr(fg, "_web_creds_ready", lambda: True)
        assert fg.resolve_source("auto", None) == "local"

    def test_auto_local_without_web_creds(self, monkeypatch):
        monkeypatch.setattr(fg, "is_local_provider_disabled", lambda _p: False)
        monkeypatch.setattr(fg, "_galaxy_db_ready", lambda _p: True)
        monkeypatch.setattr(fg, "_web_creds_ready", lambda: False)
        assert fg.resolve_source("auto", None) == "local"

    def test_auto_falls_back_to_web(self, monkeypatch):
        monkeypatch.setattr(fg, "_galaxy_db_ready", lambda _p: False)
        monkeypatch.setattr(fg, "_web_creds_ready", lambda: True)
        assert fg.resolve_source("auto", None) == "web"

    def test_auto_local_when_ready_sentinel_poisoned_env(self, monkeypatch, tmp_path):
        galaxy_db = tmp_path / "galaxy-2.0.db"
        galaxy_db.write_text("", encoding="utf-8")
        monkeypatch.setenv("GOG_GALAXY_DB", "ready")
        monkeypatch.setattr(fg, "is_local_provider_disabled", lambda _p: False)
        monkeypatch.setattr("clients.gog_galaxy_client.default_galaxy_db", lambda: galaxy_db)
        env_db = os.getenv("GOG_GALAXY_DB", "").strip()
        db_path = Path(env_db) if env_db else None
        if db_path is not None and (not db_path.is_file()):
            db_path = None
        assert fg.resolve_source("auto", db_path) == "local"

    def test_local_data_present_ignores_ready_sentinel_in_blob(self, monkeypatch, tmp_path):
        galaxy_db = tmp_path / "galaxy-2.0.db"
        galaxy_db.write_text("", encoding="utf-8")
        monkeypatch.setattr("clients.gog_galaxy_client.default_galaxy_db", lambda: galaxy_db)
        assert _local_data_present("gog_galaxy", {"GOG_GALAXY_DB": "ready"}) is True
