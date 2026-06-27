"""Tests for shared/cloud_mirror.py (M1 scaffolding)."""

from __future__ import annotations

import json
import time

import pytest

from shared import cloud_mirror as cm
from shared.profile_paths import catalog_path, personal_path


@pytest.fixture(autouse=True)
def _reset_mirror_state():
    with cm._lock:
        cm._pending.clear()
    yield
    with cm._lock:
        cm._pending.clear()


@pytest.fixture()
def profile_root(tmp_path, monkeypatch):
    from shared import profile_paths

    prof = tmp_path / "profiles"
    prof.mkdir(parents=True)
    (prof / "index.json").write_text(
        json.dumps({"active": "default", "profiles": [{"id": "default", "label": "Default"}]}),
        encoding="utf-8",
    )
    (prof / "default").mkdir()
    (prof / "default" / "data").mkdir()
    monkeypatch.setattr(profile_paths, "ROOT", tmp_path)
    monkeypatch.setattr(profile_paths, "PROFILES_DIR", prof)
    monkeypatch.setattr(profile_paths, "INDEX_FILE", prof / "index.json")
    monkeypatch.setenv("BAKLOG_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("BAKLOG_SUPABASE_URL", raising=False)
    monkeypatch.delenv("BAKLOG_SUPABASE_ANON_KEY", raising=False)
    return tmp_path


def test_mirrorable_games_json(profile_root):
    path = catalog_path("games_steam.json", profile_id="default")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")
    assert cm.mirrorable_relative_path(path, profile_id="default") == "games_steam.json"


def test_denies_cache_and_secrets(profile_root):
    cache_file = profile_root / "profiles" / "default" / "cache" / "auth" / "secrets.bin"
    cache_file.parent.mkdir(parents=True)
    cache_file.write_bytes(b"x")
    assert cm.mirrorable_relative_path(cache_file, profile_id="default") is None


def test_schedule_and_flush_gated_when_free(profile_root, monkeypatch):
    monkeypatch.setenv("BAKLOG_PLAN", "free")
    path = catalog_path("games_steam.json", profile_id="default")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")
    cm.schedule_mirror_upload(path, profile_id="default")
    cm.maybe_flush_mirror_uploads(force=True)
    assert cm._pending == {}


def test_schedule_and_flush_stub_when_pro_and_enabled(profile_root, monkeypatch, capsys):
    monkeypatch.setenv("BAKLOG_PLAN", "pro")
    from shared.pro_settings import write_pro_settings

    write_pro_settings({"cloudMirrorEnabled": True}, profile_id="default")
    path = catalog_path("games_steam.json", profile_id="default")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"games":[]}', encoding="utf-8")
    cm.schedule_mirror_upload(path, profile_id="default")
    with cm._lock:
        cm._pending["default"]["flush_at"] = time.time() - 1
    monkeypatch.setenv("BAKLOG_DEBUG", "1")
    cm.maybe_flush_mirror_uploads()
    err = capsys.readouterr().err
    assert "stub upload" in err
    assert "games_steam.json" in err


def test_personal_json_mirrorable(profile_root):
    path = personal_path(profile_id="default")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")
    assert cm.mirrorable_relative_path(path, profile_id="default") == "data/personal.json"


def test_debounce_coalesces_paths(profile_root):
    steam = catalog_path("games_steam.json", profile_id="default")
    gog = catalog_path("games_gog.json", profile_id="default")
    for p in (steam, gog):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{}", encoding="utf-8")
    cm.schedule_mirror_upload(steam, profile_id="default")
    cm.schedule_mirror_upload(gog, profile_id="default")
    with cm._lock:
        paths = cm._pending["default"]["paths"]
    assert paths == {"games_steam.json", "games_gog.json"}
