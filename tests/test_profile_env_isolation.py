import pytest

import auth.secrets as secrets_mod
from auth.manager import get_credentials, get_status, resolve_env, subprocess_env_for_profile
from auth.secrets import set_master_password_override, set_provider_blob
from shared import profile_paths
from shared.profiles import create_profile, set_active_profile


@pytest.fixture()
def isolated_profiles(tmp_path, monkeypatch):
    prof = tmp_path / "profiles"
    (prof / "default").mkdir(parents=True)
    monkeypatch.setattr(profile_paths, "ROOT", tmp_path)
    monkeypatch.setattr(profile_paths, "PROFILES_DIR", prof)
    monkeypatch.setattr(profile_paths, "INDEX_FILE", prof / "index.json")
    monkeypatch.delenv("BAKLOG_PROFILE", raising=False)
    set_master_password_override("test-passphrase-profile-env")
    secrets_mod._cache = None
    yield
    set_master_password_override(None)
    secrets_mod._cache = None


def test_missing_requirements_ignores_process_env(isolated_profiles, monkeypatch):
    create_profile("Work")
    set_active_profile("work")
    monkeypatch.setenv("BAKLOG_PROFILE", "work")
    monkeypatch.setenv("STEAM_API_KEY", "from-process-env")
    assert resolve_env("STEAM_API_KEY", allow_process_env=False) == ""
    assert resolve_env("STEAM_API_KEY", allow_process_env=True) == ""


def test_subprocess_env_uses_profile_blob_only(isolated_profiles, monkeypatch):
    create_profile("Work")
    set_active_profile("work")
    monkeypatch.setenv("BAKLOG_PROFILE", "work")
    monkeypatch.setenv("ITAD_API_KEY", "process-itad")
    set_provider_blob("itad", {"ITAD_API_KEY": "profile-itad", "status": "connected"})
    env = subprocess_env_for_profile("work")
    assert env.get("ITAD_API_KEY") == "profile-itad"
    assert env.get("BAKLOG_PROFILE") == "work"
    assert env.get("BAKLOG_DATA_DIR")
    assert env.get("ITAD_API_KEY") != "process-itad"


def test_named_profile_ignores_process_env_in_get_credentials(isolated_profiles, monkeypatch):
    create_profile("Work")
    set_active_profile("work")
    monkeypatch.setenv("BAKLOG_PROFILE", "work")
    monkeypatch.setenv("STEAM_API_KEY", "from-process-env")
    assert get_credentials("steam") == {}


def test_default_profile_merges_process_env(isolated_profiles, monkeypatch):
    set_active_profile("default")
    monkeypatch.delenv("BAKLOG_PROFILE", raising=False)
    monkeypatch.setenv("STEAM_API_KEY", "default-env-key")
    assert get_credentials("steam").get("STEAM_API_KEY") == "default-env-key"


def test_named_profile_blob_credentials_still_resolve(isolated_profiles, monkeypatch):
    create_profile("Work")
    set_active_profile("work")
    monkeypatch.setenv("BAKLOG_PROFILE", "work")
    monkeypatch.setenv("STEAM_API_KEY", "from-process-env")
    set_provider_blob("steam", {"STEAM_API_KEY": "profile-steam-key", "STEAM_ID": "1", "status": "connected"})
    assert get_credentials("steam")["STEAM_API_KEY"] == "profile-steam-key"
    assert resolve_env("STEAM_API_KEY", provider="steam") == "profile-steam-key"


def test_named_profile_auth_status_not_unverified_from_process_env(isolated_profiles, monkeypatch):
    create_profile("Work")
    set_active_profile("work")
    monkeypatch.setenv("BAKLOG_PROFILE", "work")
    monkeypatch.setenv("STEAM_API_KEY", "from-process-env")
    monkeypatch.setenv("STEAM_ID", "76561198000000000")
    steam = next((r for r in get_status() if r["key"] == "steam"))
    assert steam["status"] == "disconnected"


def test_default_profile_unverified_when_only_process_env(isolated_profiles, monkeypatch):
    set_active_profile("default")
    monkeypatch.delenv("BAKLOG_PROFILE", raising=False)
    monkeypatch.setenv("STEAM_API_KEY", "from-process-env")
    monkeypatch.setenv("STEAM_ID", "76561198000000000")
    steam = next((r for r in get_status() if r["key"] == "steam"))
    assert steam["status"] == "unverified"


def test_subprocess_env_decrypts_target_when_other_profile_active(isolated_profiles, monkeypatch):
    create_profile("Work")
    create_profile("Play")
    set_active_profile("work")
    monkeypatch.setenv("BAKLOG_PROFILE", "work")
    set_provider_blob("itad", {"ITAD_API_KEY": "work-itad", "status": "connected"})
    secrets_mod._cache = None
    set_active_profile("play")
    monkeypatch.setenv("BAKLOG_PROFILE", "play")
    secrets_mod._cache = None
    env = subprocess_env_for_profile("work")
    assert env.get("ITAD_API_KEY") == "work-itad"


def test_subprocess_env_omits_unset_provider_keys(isolated_profiles, monkeypatch):
    create_profile("Work")
    monkeypatch.setenv("STEAM_API_KEY", "leaked-in-parent")
    monkeypatch.setenv("ITAD_COUNTRY", "US")
    env = subprocess_env_for_profile("work")
    assert "STEAM_API_KEY" not in env
    assert env.get("ITAD_COUNTRY") is None
    assert env.get("BAKLOG_PROFILE") == "work"
