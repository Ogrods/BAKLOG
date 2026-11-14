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


def test_resolve_pins_account_when_local_profiles_off(
    profiles_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from shared import supabase_auth

    monkeypatch.setattr(supabase_auth, "local_profiles_enabled", lambda: False)
    uid = "550e8400-e29b-41d4-a716-446655440000"
    account_profiles.ensure_profile_for_user(uid, "a@example.com")
    assert account_profiles.resolve_request_profile_for_user(uid) == uid


def test_resolve_allows_owned_local_active(
    profiles_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from shared import supabase_auth
    from shared.profiles import create_profile

    monkeypatch.setattr(supabase_auth, "local_profiles_enabled", lambda: True)
    uid = "550e8400-e29b-41d4-a716-446655440000"
    account_profiles.ensure_profile_for_user(uid, "a@example.com")
    work = create_profile("Work", owner_user_id=uid)
    with profile_paths.mutate_index() as doc:
        doc["active"] = work["id"]
    assert account_profiles.resolve_request_profile_for_user(uid) == work["id"]


def test_resolve_falls_back_when_active_owned_by_other(
    profiles_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from shared import supabase_auth

    monkeypatch.setattr(supabase_auth, "local_profiles_enabled", lambda: True)
    uid_a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    uid_b = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    account_profiles.ensure_profile_for_user(uid_a, "a@example.com")
    account_profiles.ensure_profile_for_user(uid_b, "b@example.com")
    profile_paths.INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    with profile_paths.mutate_index() as doc:
        doc["profiles"].append(
            {
                "id": "work",
                "label": "Work",
                "created_at": "2026-01-01T00:00:00+00:00",
                "owner_user_id": uid_b,
            }
        )
        doc["active"] = "work"
    assert account_profiles.resolve_request_profile_for_user(uid_a) == uid_a


def test_unowned_local_slug_claimed_on_access(
    profiles_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from shared import supabase_auth

    monkeypatch.setattr(supabase_auth, "local_profiles_enabled", lambda: True)
    uid = "550e8400-e29b-41d4-a716-446655440000"
    account_profiles.ensure_profile_for_user(uid, "a@example.com")
    with profile_paths.mutate_index() as doc:
        doc["profiles"].append(
            {"id": "work", "label": "Work", "created_at": "2026-01-01T00:00:00+00:00"}
        )
        doc["active"] = "work"
    assert account_profiles.resolve_request_profile_for_user(uid) == "work"
    entry = next(p for p in profile_paths.load_index()["profiles"] if p["id"] == "work")
    assert entry.get("owner_user_id") == uid
