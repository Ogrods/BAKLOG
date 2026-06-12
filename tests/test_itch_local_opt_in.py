"""Per-profile opt-in for machine-wide itch_local source."""

from __future__ import annotations

from pathlib import Path

import pytest

import auth.secrets as secrets
from auth.manager import (
    _provider_state,
    enable_local,
    seed_new_profile_auth_defaults,
)
from auth.secrets import get_provider_blob, set_master_password_override
from shared import profile_paths


@pytest.fixture(autouse=True)
def isolated_default_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    prof_dir = tmp_path / "profiles"
    (prof_dir / "default").mkdir(parents=True)
    monkeypatch.setattr(profile_paths, "ROOT", tmp_path)
    monkeypatch.setattr(profile_paths, "PROFILES_DIR", prof_dir)
    monkeypatch.setattr(profile_paths, "INDEX_FILE", prof_dir / "index.json")
    monkeypatch.delenv("BAKLOG_PROFILE", raising=False)
    set_master_password_override("test-passphrase-itch-local-opt-in")
    secrets._cache = None
    target = profile_paths.auth_dir(profile_id="default")
    saved = (
        secrets.AUTH_DIR,
        secrets.SECRETS_FILE,
        secrets.MASTER_KEY_FILE,
        secrets._cache,
    )
    secrets.AUTH_DIR = target
    secrets.SECRETS_FILE = target / "secrets.bin"
    secrets.MASTER_KEY_FILE = target / ".master_key"
    yield
    set_master_password_override(None)
    secrets.AUTH_DIR, secrets.SECRETS_FILE, secrets.MASTER_KEY_FILE, secrets._cache = saved


def test_itch_local_requires_enabled_even_when_butler_db_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("auth.manager.platform_supported", lambda platforms: True)
    monkeypatch.setattr("auth.manager._local_data_present", lambda provider, blob: True)
    assert _provider_state("itch_local") == "disconnected"
    enable_local("itch_local")
    assert get_provider_blob("itch_local").get("enabled") is True
    assert _provider_state("itch_local") == "connected"


def test_seed_new_profile_auth_defaults_disables_itch_local(tmp_path: Path) -> None:
    profile_id = "work"
    seed_new_profile_auth_defaults(profile_id)
    saved = (
        secrets.AUTH_DIR,
        secrets.SECRETS_FILE,
        secrets.MASTER_KEY_FILE,
        secrets._cache,
    )
    target = profile_paths.auth_dir(profile_id=profile_id)
    secrets.AUTH_DIR = target
    secrets.SECRETS_FILE = target / "secrets.bin"
    secrets.MASTER_KEY_FILE = target / ".master_key"
    secrets._cache = None
    try:
        blob = get_provider_blob("itch_local")
        assert blob.get("disabled") is True
        assert "enabled" not in blob
    finally:
        secrets.AUTH_DIR, secrets.SECRETS_FILE, secrets.MASTER_KEY_FILE, secrets._cache = saved
