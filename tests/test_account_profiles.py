"""Tests for Supabase user -> profile mapping."""
from __future__ import annotations

from pathlib import Path

import pytest

from shared import account_profiles, profile_paths


@pytest.fixture()
def profiles_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    prof = tmp_path / "profiles"
    monkeypatch.setattr(profile_paths, "ROOT", tmp_path)
    monkeypatch.setattr(profile_paths, "PROFILES_DIR", prof)
    monkeypatch.setattr(profile_paths, "INDEX_FILE", prof / "index.json")
    return prof


def test_ensure_profile_for_user_creates_once(profiles_root: Path) -> None:
    uid = "550e8400-e29b-41d4-a716-446655440000"
    pid = account_profiles.ensure_profile_for_user(uid, "friend@example.com")
    assert pid == uid
    dest = profiles_root / uid
    assert dest.is_dir()
    assert (dest / "data").is_dir()
    pid2 = account_profiles.ensure_profile_for_user(uid, "friend@example.com")
    assert pid2 == pid
    doc = profile_paths.load_index()
    matches = [p for p in doc.get("profiles", []) if p.get("id") == uid]
    assert len(matches) == 1


def test_profile_id_for_user_normalizes_case() -> None:
    uid = "550E8400-E29B-41D4-A716-446655440000"
    assert account_profiles.profile_id_for_user(uid) == uid.lower()
