"""Tests for the one-time .env -> encrypted blob migration (default profile)."""

from __future__ import annotations

from pathlib import Path

import pytest

import auth.secrets as secrets
from auth.manager import (
    _LEGACY_ENV_ALIASES,
    get_provider_blob,
    import_env_credentials,
    mark_connected,
)
from auth.registry import PROVIDERS
from auth.secrets import set_master_password_override
from shared import profile_paths


@pytest.fixture(autouse=True)
def isolated_default_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point profile paths at a tmp tree with an explicit default profile dir."""
    prof_dir = tmp_path / "profiles"
    (prof_dir / "default").mkdir(parents=True)
    monkeypatch.setattr(profile_paths, "ROOT", tmp_path)
    monkeypatch.setattr(profile_paths, "PROFILES_DIR", prof_dir)
    monkeypatch.setattr(profile_paths, "INDEX_FILE", prof_dir / "index.json")
    monkeypatch.delenv("BAKLOG_PROFILE", raising=False)
    # Deterministic encryption without touching the OS keyring.
    set_master_password_override("test-passphrase-for-env-import")
    secrets._cache = None
    # Clear every provider env key (and legacy alias) so the real environment /
    # a developer's .env never leaks into the import under test.
    for spec in PROVIDERS.values():
        for key in spec.env_keys:
            monkeypatch.delenv(key, raising=False)
    for aliases in _LEGACY_ENV_ALIASES.values():
        for key in aliases:
            monkeypatch.delenv(key, raising=False)
    yield
    set_master_password_override(None)
    secrets._cache = None


def _read_default_blob(provider: str) -> dict:
    """Read a provider blob from the default profile's secrets store."""
    target = profile_paths.auth_dir(profile_id="default")
    saved = (secrets.AUTH_DIR, secrets.SECRETS_FILE, secrets.MASTER_KEY_FILE, secrets._cache)
    secrets.AUTH_DIR = target
    secrets.SECRETS_FILE = target / "secrets.bin"
    secrets.MASTER_KEY_FILE = target / ".master_key"
    secrets._cache = None
    try:
        return get_provider_blob(provider)
    finally:
        secrets.AUTH_DIR, secrets.SECRETS_FILE, secrets.MASTER_KEY_FILE, secrets._cache = saved


def test_imports_env_into_default_blob(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ITCH_API_KEY", "itch-from-env")
    monkeypatch.setenv("STEAM_API_KEY", "steam-key")
    monkeypatch.setenv("STEAM_ID", "76561198000000000")

    imported = import_env_credentials(profile_id="default")

    assert "itch" in imported
    assert "steam" in imported
    itch = _read_default_blob("itch")
    assert itch["status"] == "connected"
    assert itch["ITCH_API_KEY"] == "itch-from-env"
    steam = _read_default_blob("steam")
    assert steam["STEAM_API_KEY"] == "steam-key"
    assert steam["STEAM_ID"] == "76561198000000000"


def test_skips_provider_with_no_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ITCH_API_KEY", "only-itch")

    imported = import_env_credentials(profile_id="default")

    assert imported == ["itch"]
    assert _read_default_blob("gog") == {}


def test_does_not_overwrite_connected_provider(monkeypatch: pytest.MonkeyPatch):
    # Pre-connect gog directly in the default blob.
    target = profile_paths.auth_dir(profile_id="default")
    saved = (secrets.AUTH_DIR, secrets.SECRETS_FILE, secrets.MASTER_KEY_FILE, secrets._cache)
    secrets.AUTH_DIR = target
    secrets.SECRETS_FILE = target / "secrets.bin"
    secrets.MASTER_KEY_FILE = target / ".master_key"
    secrets._cache = None
    try:
        mark_connected("gog", {"GOG_AL": "real-session"})
    finally:
        secrets.AUTH_DIR, secrets.SECRETS_FILE, secrets.MASTER_KEY_FILE, secrets._cache = saved

    monkeypatch.setenv("GOG_AL", "env-session-should-be-ignored")
    imported = import_env_credentials(profile_id="default")

    assert "gog" not in imported
    assert _read_default_blob("gog")["GOG_AL"] == "real-session"


def test_skips_local_amazon_provider(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AMAZON_GAMES_SQL_DIR", "C:/whatever")
    imported = import_env_credentials(profile_id="default")
    assert "amazon" not in imported
