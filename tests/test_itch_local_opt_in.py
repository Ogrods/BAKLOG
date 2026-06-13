"""Per-profile opt-in for machine-wide local sources (itch, GOG Galaxy, Amazon)."""

from __future__ import annotations

from pathlib import Path

import pytest

import auth.secrets as secrets
from auth.manager import (
    _provider_state,
    _with_profile_secrets,
    enable_local,
    get_status,
    seed_new_profile_auth_defaults,
)
from auth.secrets import get_provider_blob, set_master_password_override
from shared import profile_paths
from shared.profiles import create_profile, set_active_profile

_LOCAL_PROVIDERS = ("itch_local", "gog_galaxy", "amazon")


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
    # Read back through the same profile-scoped context the seed write used, so
    # the HKDF subkey is derived for "work" (not the active profile).
    with _with_profile_secrets(profile_id):
        blob = get_provider_blob("itch_local")
        assert blob.get("disabled") is True
        assert "enabled" not in blob


def test_seed_new_profile_auth_defaults_disables_all_local_providers() -> None:
    profile_id = "work"
    seed_new_profile_auth_defaults(profile_id)
    with _with_profile_secrets(profile_id):
        for key in _LOCAL_PROVIDERS:
            blob = get_provider_blob(key)
            assert blob.get("disabled") is True
            if key == "itch_local":
                assert "enabled" not in blob


def test_create_profile_local_providers_disconnected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("auth.manager.platform_supported", lambda platforms: True)
    monkeypatch.setattr("auth.manager._local_data_present", lambda provider, blob: True)
    create_profile("Work")
    set_active_profile("work")
    target = profile_paths.auth_dir(profile_id="work")
    secrets.AUTH_DIR = target
    secrets.SECRETS_FILE = target / "secrets.bin"
    secrets.MASTER_KEY_FILE = target / ".master_key"
    secrets._cache = None
    statuses = {row["key"]: row["status"] for row in get_status()}
    for key in _LOCAL_PROVIDERS:
        assert statuses[key] == "disconnected"
