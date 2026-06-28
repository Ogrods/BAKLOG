import json

import pytest

import auth.secrets as secrets
from auth.manager import (
    _provider_state,
    _with_profile_secrets,
    enable_local,
    get_status,
    migrate_existing_itch_local_opt_in,
    seed_new_profile_auth_defaults,
)
from auth.secrets import get_provider_blob, set_master_password_override
from shared import profile_paths
from shared.profiles import create_profile, set_active_profile

_LOCAL_PROVIDERS = ("itch_local", "gog_galaxy", "amazon")


@pytest.fixture(autouse=True)
def isolated_default_profile(tmp_path, monkeypatch):
    prof_dir = tmp_path / "profiles"
    (prof_dir / "default").mkdir(parents=True)
    monkeypatch.setattr(profile_paths, "ROOT", tmp_path)
    monkeypatch.setattr(profile_paths, "PROFILES_DIR", prof_dir)
    monkeypatch.setattr(profile_paths, "INDEX_FILE", prof_dir / "index.json")
    monkeypatch.delenv("BAKLOG_PROFILE", raising=False)
    set_master_password_override("test-passphrase-itch-local-opt-in")
    secrets._cache = None
    target = profile_paths.auth_dir(profile_id="default")
    saved = (secrets.AUTH_DIR, secrets.SECRETS_FILE, secrets.MASTER_KEY_FILE, secrets._cache)
    secrets.AUTH_DIR = target
    secrets.SECRETS_FILE = target / "secrets.bin"
    secrets.MASTER_KEY_FILE = target / ".master_key"
    yield
    set_master_password_override(None)
    secrets.AUTH_DIR, secrets.SECRETS_FILE, secrets.MASTER_KEY_FILE, secrets._cache = saved


def test_itch_local_requires_enabled_even_when_butler_db_present(monkeypatch):
    monkeypatch.setattr("auth.manager.platform_supported", lambda platforms: True)
    monkeypatch.setattr("auth.manager._local_data_present", lambda provider, blob: True)
    assert _provider_state("itch_local") == "disconnected"
    enable_local("itch_local")
    assert get_provider_blob("itch_local").get("enabled") is True
    assert _provider_state("itch_local") == "connected"


def test_seed_new_profile_auth_defaults_disables_itch_local(tmp_path):
    profile_id = "work"
    seed_new_profile_auth_defaults(profile_id)
    with _with_profile_secrets(profile_id):
        blob = get_provider_blob("itch_local")
        assert blob.get("disabled") is True
        assert "enabled" not in blob


def test_seed_new_profile_auth_defaults_disables_all_local_providers():
    profile_id = "work"
    seed_new_profile_auth_defaults(profile_id)
    with _with_profile_secrets(profile_id):
        for key in _LOCAL_PROVIDERS:
            blob = get_provider_blob(key)
            assert blob.get("disabled") is True
            if key == "itch_local":
                assert "enabled" not in blob


def _write_itch_catalog(profile_id, game_count):
    path = profile_paths.catalog_path("games_itch.json", profile_id=profile_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    games = [{"id": str(i), "name": f"Game {i}"} for i in range(game_count)]
    path.write_text(json.dumps({"game_count": game_count, "games": games}), encoding="utf-8")


def test_migration_opts_in_existing_profile_with_itch_library(monkeypatch):
    monkeypatch.setattr("auth.manager.platform_supported", lambda platforms: True)
    monkeypatch.setattr("auth.manager._local_data_present", lambda provider, blob: True)
    _write_itch_catalog("default", 12)
    assert _provider_state("itch_local") == "disconnected"
    notes = migrate_existing_itch_local_opt_in()
    assert any(("default" in n for n in notes))
    secrets._cache = None
    assert get_provider_blob("itch_local").get("enabled") is True
    assert _provider_state("itch_local") == "connected"


def test_migration_skips_profile_without_itch_library():
    notes = migrate_existing_itch_local_opt_in()
    assert not any(("opted in" in n for n in notes))
    secrets._cache = None
    assert "enabled" not in get_provider_blob("itch_local")


def test_migration_leaves_explicitly_disconnected_profile_untouched():
    _write_itch_catalog("default", 5)
    seed_new_profile_auth_defaults("default")
    secrets._cache = None
    migrate_existing_itch_local_opt_in()
    secrets._cache = None
    blob = get_provider_blob("itch_local")
    assert blob.get("disabled") is True
    assert "enabled" not in blob


def test_create_profile_local_providers_disconnected(monkeypatch):
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
