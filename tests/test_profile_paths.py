import json
from pathlib import Path

import pytest

from shared import profile_paths, profiles
from shared.profile_paths import normalize_profile_id


@pytest.fixture
def isolated_profiles(tmp_path, monkeypatch):
    prof_dir = tmp_path / "profiles"
    monkeypatch.setattr(profile_paths, "ROOT", tmp_path)
    monkeypatch.setattr(profile_paths, "PROFILES_DIR", prof_dir)
    monkeypatch.setattr(profile_paths, "INDEX_FILE", prof_dir / "index.json")
    monkeypatch.delenv("BAKLOG_PROFILE", raising=False)
    return tmp_path


def test_legacy_layout_uses_repo_root(isolated_profiles):
    assert profile_paths.is_legacy_layout() is True
    assert profile_paths.profile_root() == isolated_profiles
    assert profile_paths.catalog_path("games_steam.json") == isolated_profiles / "games_steam.json"
    assert profile_paths.personal_path() == isolated_profiles / "data" / "personal.json"
    assert profile_paths.auth_dir() == isolated_profiles / "cache" / "auth"


def test_scoped_profile_uses_profiles_dir(isolated_profiles):
    scoped = isolated_profiles / "profiles" / "work"
    scoped.mkdir(parents=True)
    (scoped / "games_steam.json").write_text('{"game_count":0,"games":[]}', encoding="utf-8")
    index = {
        "active": "work",
        "profiles": [
            {"id": "default", "label": "Default", "created_at": "t"},
            {"id": "work", "label": "Work", "created_at": "t"},
        ],
    }
    (isolated_profiles / "profiles" / "index.json").write_text(json.dumps(index), encoding="utf-8")
    assert profile_paths.is_legacy_layout("default") is True
    assert profile_paths.is_legacy_layout("work") is False
    assert profile_paths.get_active_profile_id() == "work"
    assert profile_paths.catalog_path("games_steam.json") == scoped / "games_steam.json"


def test_env_override_active_profile(isolated_profiles, monkeypatch):
    work = isolated_profiles / "profiles" / "work"
    work.mkdir(parents=True)
    monkeypatch.setenv("BAKLOG_PROFILE", "work")
    assert profile_paths.get_active_profile_id() == "work"
    assert profile_paths.profile_root() == work


def test_resolve_catalog_path_relative(isolated_profiles):
    p = profile_paths.resolve_catalog_path(Path("games_epic.json"))
    assert p == isolated_profiles / "games_epic.json"


def test_create_profile_migrates_default_copy(isolated_profiles):
    (isolated_profiles / "games_steam.json").write_text(
        '{"game_count":1,"games":[{"id":"1","name":"A"}]}', encoding="utf-8"
    )
    (isolated_profiles / "data").mkdir()
    (isolated_profiles / "data" / "personal.json").write_text('{"personal":{}}', encoding="utf-8")
    created = profiles.create_profile("Work")
    assert created["id"] == "work"
    default_dir = isolated_profiles / "profiles" / "default"
    assert default_dir.is_dir()
    assert (default_dir / "games_steam.json").is_file()
    assert (default_dir / "data" / "personal.json").is_file()
    work_dir = isolated_profiles / "profiles" / "work"
    assert work_dir.is_dir()
    assert not (work_dir / "games_steam.json").exists()


def test_normalize_profile_id_rejects_unsafe():
    with pytest.raises(ValueError):
        normalize_profile_id("..")
    with pytest.raises(ValueError):
        normalize_profile_id("bad id")


def test_finalize_migration_when_default_dir_exists_without_marker(isolated_profiles):
    (isolated_profiles / "games_steam.json").write_text("{}", encoding="utf-8")
    default_dir = isolated_profiles / "profiles" / "default"
    default_dir.mkdir(parents=True)
    (default_dir / "games_steam.json").write_text("{}", encoding="utf-8")
    assert profile_paths.is_legacy_layout("default") is True
    profiles.finalize_default_profile_migration()
    assert profile_paths.migration_complete_path().is_file()
    assert profile_paths.is_legacy_layout("default") is False
    assert profile_paths.profile_root("default") == default_dir


def test_migration_marker_gates_legacy_layout(isolated_profiles):
    (isolated_profiles / "games_steam.json").write_text("{}", encoding="utf-8")
    default_dir = isolated_profiles / "profiles" / "default"
    default_dir.mkdir(parents=True)
    assert profile_paths.is_legacy_layout() is True
    profiles.ensure_default_profile_dir()
    assert profile_paths.migration_complete_path().is_file()
    assert profile_paths.is_legacy_layout() is False


def test_migration_resumes_missing_files(isolated_profiles):
    (isolated_profiles / "games_steam.json").write_text('{"game_count":1,"games":[]}', encoding="utf-8")
    default_dir = isolated_profiles / "profiles" / "default"
    default_dir.mkdir(parents=True)
    profiles.ensure_default_profile_dir()
    assert (default_dir / "games_steam.json").is_file()
    (default_dir / "games_steam.json").unlink()
    (isolated_profiles / "games_gog.json").write_text('{"game_count":0,"games":[]}', encoding="utf-8")
    profiles.ensure_default_profile_dir()
    assert (default_dir / "games_steam.json").is_file()
    assert (default_dir / "games_gog.json").is_file()


def test_delete_default_allowed_when_not_active(isolated_profiles):
    (isolated_profiles / "games_steam.json").write_text("{}", encoding="utf-8")
    profiles.create_profile("Work")
    doc = profile_paths.load_index()
    doc["active"] = "work"
    profile_paths.save_index(doc)
    profiles.delete_profile("default")
    assert not (isolated_profiles / "profiles" / "default").is_dir()
    remaining = profile_paths.load_index()["profiles"]
    assert len(remaining) == 1
    assert remaining[0]["id"] == "work"


def test_delete_profile_refuses_active(isolated_profiles):
    profiles.create_profile("Work")
    doc = profile_paths.load_index()
    doc["active"] = "work"
    profile_paths.save_index(doc)
    with pytest.raises(ValueError, match="active"):
        profiles.delete_profile("work")
