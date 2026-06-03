"""Tests for shared/profile_paths.py and shared/profiles.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared import profile_paths, profiles
from shared.profile_paths import normalize_profile_id


@pytest.fixture
def isolated_profiles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point profiles + ROOT at tmp_path for isolation."""
    prof_dir = tmp_path / "profiles"
    monkeypatch.setattr(profile_paths, "ROOT", tmp_path)
    monkeypatch.setattr(profile_paths, "PROFILES_DIR", prof_dir)
    monkeypatch.setattr(profile_paths, "INDEX_FILE", prof_dir / "index.json")
    monkeypatch.delenv("BAKLOG_PROFILE", raising=False)
    return tmp_path


def test_legacy_layout_uses_repo_root(isolated_profiles: Path) -> None:
    assert profile_paths.is_legacy_layout() is True
    assert profile_paths.profile_root() == isolated_profiles
    assert profile_paths.catalog_path("games_steam.json") == isolated_profiles / "games_steam.json"
    assert profile_paths.personal_path() == isolated_profiles / "data" / "personal.json"
    assert profile_paths.auth_dir() == isolated_profiles / "cache" / "auth"


def test_scoped_profile_uses_profiles_dir(isolated_profiles: Path) -> None:
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
    (isolated_profiles / "profiles" / "index.json").write_text(
        json.dumps(index), encoding="utf-8"
    )
    assert profile_paths.is_legacy_layout("default") is True
    assert profile_paths.is_legacy_layout("work") is False
    assert profile_paths.get_active_profile_id() == "work"
    assert profile_paths.catalog_path("games_steam.json") == scoped / "games_steam.json"


def test_env_override_active_profile(isolated_profiles: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    work = isolated_profiles / "profiles" / "work"
    work.mkdir(parents=True)
    monkeypatch.setenv("BAKLOG_PROFILE", "work")
    assert profile_paths.get_active_profile_id() == "work"
    assert profile_paths.profile_root() == work


def test_resolve_catalog_path_relative(isolated_profiles: Path) -> None:
    p = profile_paths.resolve_catalog_path(Path("games_epic.json"))
    assert p == isolated_profiles / "games_epic.json"


def test_create_profile_migrates_default_copy(isolated_profiles: Path) -> None:
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


def test_normalize_profile_id_rejects_unsafe() -> None:
    with pytest.raises(ValueError):
        normalize_profile_id("..")
    with pytest.raises(ValueError):
        normalize_profile_id("bad id")


def test_migration_resumes_missing_files(isolated_profiles: Path) -> None:
    (isolated_profiles / "games_steam.json").write_text(
        '{"game_count":1,"games":[]}', encoding="utf-8"
    )
    default_dir = isolated_profiles / "profiles" / "default"
    default_dir.mkdir(parents=True)
    profiles.ensure_default_profile_dir()
    assert (default_dir / "games_steam.json").is_file()
    (default_dir / "games_steam.json").unlink()
    (isolated_profiles / "games_gog.json").write_text(
        '{"game_count":0,"games":[]}', encoding="utf-8"
    )
    profiles.ensure_default_profile_dir()
    assert (default_dir / "games_steam.json").is_file()
    assert (default_dir / "games_gog.json").is_file()


def test_delete_default_blocked_after_migration(isolated_profiles: Path) -> None:
    (isolated_profiles / "games_steam.json").write_text("{}", encoding="utf-8")
    profiles.create_profile("Work")
    with pytest.raises(ValueError, match="default"):
        profiles.delete_profile("default")


def test_delete_profile_refuses_active(isolated_profiles: Path) -> None:
    profiles.create_profile("Work")
    doc = profile_paths.load_index()
    doc["active"] = "work"
    profile_paths.save_index(doc)
    with pytest.raises(ValueError, match="active"):
        profiles.delete_profile("work")
