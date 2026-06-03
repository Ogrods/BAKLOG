"""Epic OAuth session file is stored under the active profile's cache."""

from __future__ import annotations

from pathlib import Path

import pytest

from epic_client import EpicClient, default_epic_cache_dir
from shared import profile_paths
from shared.profiles import create_profile


@pytest.fixture()
def isolated_profiles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prof = tmp_path / "profiles"
    (prof / "default").mkdir(parents=True)
    monkeypatch.setattr(profile_paths, "ROOT", tmp_path)
    monkeypatch.setattr(profile_paths, "PROFILES_DIR", prof)
    monkeypatch.setattr(profile_paths, "INDEX_FILE", prof / "index.json")
    monkeypatch.delenv("BAKLOG_PROFILE", raising=False)


def test_epic_session_under_named_profile(
    isolated_profiles: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_profile("Work")
    monkeypatch.setenv("BAKLOG_PROFILE", "work")

    cache_dir = default_epic_cache_dir()
    assert cache_dir == profile_paths.epic_cache_dir(profile_id="work")

    client = EpicClient(cache_dir=cache_dir)
    client._access_token = "access"
    client._refresh_token = "refresh"
    client._account_id = "acct"
    client._save_session()

    session = cache_dir / "session.json"
    assert session.is_file()
    assert not (profile_paths.ROOT / "cache" / "epic" / "session.json").is_file()


def test_epic_migrates_legacy_session_into_profile_cache(
    isolated_profiles: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    create_profile("Work")
    monkeypatch.setenv("BAKLOG_PROFILE", "work")

    legacy_dir = tmp_path / "cache" / "epic"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "session.json").write_text(
        '{"refresh_token": "old", "account_id": "1"}',
        encoding="utf-8",
    )

    cache_dir = default_epic_cache_dir()
    profile_session = cache_dir / "session.json"
    if profile_session.exists():
        profile_session.unlink()

    client = EpicClient(cache_dir=cache_dir)
    client._migrate_legacy_session()
    assert profile_session.is_file()
    loaded = client._load_session()
    assert loaded is not None
    assert loaded.get("refresh_token") == "old"
