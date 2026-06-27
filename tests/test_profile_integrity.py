"""Profile index integrity: reconcile, corrupt quarantine, reserved ids, delete safety."""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from shared import profile_paths, profiles
from shared.profile_paths import normalize_profile_id, reconcile_profile_store, unique_profile_id_for_doc


@pytest.fixture
def isolated_profiles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    prof_dir = tmp_path / "profiles"
    monkeypatch.setattr(profile_paths, "ROOT", tmp_path)
    monkeypatch.setattr(profile_paths, "PROFILES_DIR", prof_dir)
    monkeypatch.setattr(profile_paths, "INDEX_FILE", prof_dir / "index.json")
    monkeypatch.delenv("BAKLOG_PROFILE", raising=False)
    return tmp_path


@pytest.fixture(autouse=True)
def _reset_pin_state() -> None:
    """PIN failure/lockout dicts are module-level; isolate them per test."""
    profiles._pin_failures.clear()
    profiles._pin_lock_until.clear()
    yield
    profiles._pin_failures.clear()
    profiles._pin_lock_until.clear()


def test_reserved_profile_ids_rejected() -> None:
    for bad in ("con", "nul", "com1", "lpt9"):
        with pytest.raises(ValueError):
            normalize_profile_id(bad)


def test_unique_profile_id_avoids_orphan_dir(isolated_profiles: Path) -> None:
    orphan = isolated_profiles / "profiles" / "work"
    orphan.mkdir(parents=True)
    assert profile_paths.unique_profile_id("Work") == "work-2"


def test_reconcile_adopts_orphan_profile_dir(isolated_profiles: Path) -> None:
    orphan = isolated_profiles / "profiles" / "play"
    orphan.mkdir(parents=True)
    (orphan / "data").mkdir()
    with patch("shared.supabase_auth.auth_enabled", return_value=False):
        notes = reconcile_profile_store()
    doc = profile_paths.load_index()
    ids = {p["id"] for p in doc["profiles"]}
    assert "play" in ids
    assert any("adopted orphan" in n for n in notes)


def test_reconcile_skips_adoption_when_auth_enabled(isolated_profiles: Path) -> None:
    orphan = isolated_profiles / "profiles" / "play"
    orphan.mkdir(parents=True)
    with patch("shared.supabase_auth.auth_enabled", return_value=True):
        with patch("shared.supabase_auth.local_profiles_enabled", return_value=False):
            notes = reconcile_profile_store()
    doc = profile_paths.load_index()
    ids = {p["id"] for p in doc["profiles"]}
    assert "play" not in ids
    assert any("orphan profile dir not in index" in n for n in notes)


def test_reconcile_adopts_orphans_when_auth_and_local_profiles(isolated_profiles: Path) -> None:
    orphan = isolated_profiles / "profiles" / "play"
    orphan.mkdir(parents=True)
    (orphan / "data").mkdir()
    with patch("shared.supabase_auth.auth_enabled", return_value=True):
        with patch("shared.supabase_auth.local_profiles_enabled", return_value=True):
            notes = reconcile_profile_store()
    doc = profile_paths.load_index()
    ids = {p["id"] for p in doc["profiles"]}
    assert "play" in ids
    assert any("adopted orphan" in n for n in notes)


def test_reconcile_materializes_index_when_profile_dir_exists_without_index(
    isolated_profiles: Path,
) -> None:
    default_dir = isolated_profiles / "profiles" / "default"
    default_dir.mkdir(parents=True)
    (default_dir / "data").mkdir()
    assert not (isolated_profiles / "profiles" / "index.json").is_file()
    with patch("shared.supabase_auth.auth_enabled", return_value=True):
        with patch("shared.supabase_auth.local_profiles_enabled", return_value=True):
            notes = reconcile_profile_store()
    assert (isolated_profiles / "profiles" / "index.json").is_file()
    assert any("materialized profiles/index.json" in n for n in notes)
    doc = profile_paths.load_index()
    assert doc["active"] == "default"


def test_quarantined_delete_dir_not_readopted(
    isolated_profiles: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profiles.create_profile("Work")
    profiles.create_profile("Play")
    doc = profile_paths.load_index()
    doc["active"] = "play"
    profile_paths.save_index(doc)

    original_rmtree = shutil.rmtree

    def keep_trash(path: Path | str, *args: object, **kwargs: object) -> None:
        name = Path(path).name
        if name.startswith(".trash-work-"):
            return
        original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", keep_trash)
    profiles.delete_profile("work")
    assert "work" not in {p["id"] for p in profile_paths.load_index()["profiles"]}
    trash_dirs = [
        p
        for p in (isolated_profiles / "profiles").iterdir()
        if p.is_dir() and p.name.startswith(".trash-work-")
    ]
    assert trash_dirs
    with patch("shared.supabase_auth.auth_enabled", return_value=False):
        reconcile_profile_store()
    assert "work" not in {p["id"] for p in profile_paths.load_index()["profiles"]}


def test_create_profile_reserves_index_before_mkdir(
    isolated_profiles: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen_in_index = {"work": False}
    original_mkdir = Path.mkdir

    def tracking_mkdir(self: Path, *args: object, **kwargs: object) -> None:
        if self.name == "work" and "profiles" in self.as_posix():
            doc = profile_paths.load_index()
            ids = {p["id"] for p in doc.get("profiles", []) if isinstance(p, dict)}
            seen_in_index["work"] = "work" in ids
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", tracking_mkdir)
    created = profiles.create_profile("Work")
    assert created["id"] == "work"
    assert seen_in_index["work"] is True


def test_unique_profile_id_for_doc_avoids_index_and_disk(isolated_profiles: Path) -> None:
    doc = profile_paths.load_index()
    (isolated_profiles / "profiles" / "work").mkdir(parents=True)
    assert unique_profile_id_for_doc("Work", doc) == "work-2"


def test_create_profile_rejects_overlong_label(isolated_profiles: Path) -> None:
    too_long = "x" * (profiles.LABEL_MAX_LEN + 1)
    with pytest.raises(ValueError, match="characters or fewer"):
        profiles.create_profile(too_long)
    # Boundary: exactly the cap is accepted.
    ok = profiles.create_profile("y" * profiles.LABEL_MAX_LEN)
    assert ok["label"] == "y" * profiles.LABEL_MAX_LEN


def test_rename_profile_rejects_overlong_label(isolated_profiles: Path) -> None:
    profiles.create_profile("Work")
    with pytest.raises(ValueError, match="characters or fewer"):
        profiles.rename_profile("work", "z" * (profiles.LABEL_MAX_LEN + 1))


def test_corrupt_index_quarantined_not_silently_overwritten(isolated_profiles: Path) -> None:
    index = isolated_profiles / "profiles" / "index.json"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text("{not json", encoding="utf-8")
    doc = profile_paths.load_index()
    assert doc["active"] == profile_paths.DEFAULT_PROFILE_ID
    quarantined = list(index.parent.glob("index.json.corrupt-*"))
    assert quarantined
    assert not index.exists()


def test_save_index_rejects_active_not_in_profiles(isolated_profiles: Path) -> None:
    doc = profile_paths.load_index()
    doc["active"] = "missing"
    with pytest.raises(ValueError, match="not in profiles"):
        profile_paths.save_index(doc)


def test_rename_locked_profile_requires_pin(isolated_profiles: Path) -> None:
    profiles.create_profile("Work")
    profiles.set_profile_pin("work", "1234")
    with pytest.raises(ValueError, match="current PIN is incorrect"):
        profiles.rename_profile("work", "Renamed")
    with pytest.raises(ValueError, match="current PIN is incorrect"):
        profiles.rename_profile("work", "Renamed", current_pin="0000")
    updated = profiles.rename_profile("work", "Renamed", current_pin="1234")
    assert updated["label"] == "Renamed"


def test_delete_profile_clears_pin_lockout(isolated_profiles: Path) -> None:
    profiles.create_profile("Work")
    profiles.create_profile("Play")
    doc = profile_paths.load_index()
    doc["active"] = "work"
    profile_paths.save_index(doc)
    profiles.set_profile_pin("play", "1234")
    profiles.delete_profile("play", current_pin="1234")
    profiles.create_profile("Play")
    assert profiles.pin_rate_limit_error("play") is None


def test_delete_locked_profile_requires_pin(isolated_profiles: Path) -> None:
    profiles.create_profile("Work")
    profiles.create_profile("Play")
    doc = profile_paths.load_index()
    doc["active"] = "work"
    profile_paths.save_index(doc)
    profiles.set_profile_pin("play", "1234")
    with pytest.raises(ValueError, match="current PIN is incorrect"):
        profiles.delete_profile("play")
    with pytest.raises(ValueError, match="current PIN is incorrect"):
        profiles.delete_profile("play", current_pin="0000")
    # Profile survives the failed attempts.
    assert "play" in {p["id"] for p in profile_paths.load_index()["profiles"]}
    profiles.delete_profile("play", current_pin="1234")
    assert "play" not in {p["id"] for p in profile_paths.load_index()["profiles"]}


def test_delete_unlocked_profile_ignores_pin_arg(isolated_profiles: Path) -> None:
    profiles.create_profile("Work")
    profiles.create_profile("Play")
    doc = profile_paths.load_index()
    doc["active"] = "work"
    profile_paths.save_index(doc)
    profiles.delete_profile("play")
    assert "play" not in {p["id"] for p in profile_paths.load_index()["profiles"]}


def test_delete_locked_profile_lockout_blocks(isolated_profiles: Path) -> None:
    profiles.create_profile("Work")
    profiles.create_profile("Play")
    doc = profile_paths.load_index()
    doc["active"] = "work"
    profile_paths.save_index(doc)
    profiles.set_profile_pin("play", "1234")
    for _ in range(profiles._PIN_MAX_ATTEMPTS):
        with pytest.raises(ValueError):
            profiles.delete_profile("play", current_pin="0000")
    # Now locked out: even the correct PIN is refused with the lockout message.
    with pytest.raises(ValueError, match="too many PIN attempts"):
        profiles.delete_profile("play", current_pin="1234")
    assert "play" in {p["id"] for p in profile_paths.load_index()["profiles"]}


def test_delete_profile_blocks_effective_active_via_env(
    isolated_profiles: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profiles.create_profile("Work")
    doc = profile_paths.load_index()
    doc["active"] = "default"
    profile_paths.save_index(doc)
    monkeypatch.setenv("BAKLOG_PROFILE", "work")
    with pytest.raises(ValueError, match="active"):
        profiles.delete_profile("work")
