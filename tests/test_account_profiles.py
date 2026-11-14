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


def test_ensure_profile_activates_when_local_profiles_off(
    profiles_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from shared import supabase_auth

    monkeypatch.setattr(supabase_auth, "local_profiles_enabled", lambda: False)
    uid = "550e8400-e29b-41d4-a716-446655440000"
    # Leftover empty default as active (NUC install shape).
    profile_paths.INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    profile_paths.INDEX_FILE.write_text(
        '{"active":"default","profiles":[{"id":"default","label":"Default"}]}',
        encoding="utf-8",
    )
    pid = account_profiles.ensure_profile_for_user(uid, "dan@example.com")
    assert profile_paths.load_index().get("active") == pid
    # Idempotent re-bind keeps account active.
    account_profiles.ensure_profile_for_user(uid, "dan@example.com")
    assert profile_paths.load_index().get("active") == pid


def test_ensure_profile_leaves_active_when_local_profiles_on(
    profiles_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from shared import supabase_auth

    monkeypatch.setattr(supabase_auth, "local_profiles_enabled", lambda: True)
    uid = "550e8400-e29b-41d4-a716-446655440000"
    profile_paths.INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    profile_paths.INDEX_FILE.write_text(
        '{"active":"default","profiles":[{"id":"default","label":"Default"}]}',
        encoding="utf-8",
    )
    account_profiles.ensure_profile_for_user(uid, "dan@example.com")
    assert profile_paths.load_index().get("active") == "default"


def test_profile_id_for_user_normalizes_case() -> None:
    uid = "550E8400-E29B-41D4-A716-446655440000"
    assert account_profiles.profile_id_for_user(uid) == uid.lower()
