"""Tests for encrypted auth credential store."""

from __future__ import annotations

from pathlib import Path

import pytest

from auth.manager import disconnect, get_credentials, mark_connected, resolve_env
from auth.registry import spec_for
from auth.secrets import _secrets_file, load_doc, set_master_password_override


@pytest.fixture(autouse=True)
def _isolated_auth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    auth_dir = tmp_path / "auth"
    monkeypatch.setattr("auth.secrets.AUTH_DIR", auth_dir)
    monkeypatch.setattr("auth.secrets.SECRETS_FILE", auth_dir / "secrets.bin")
    monkeypatch.setattr("auth.secrets.MASTER_KEY_FILE", auth_dir / ".master_key")
    monkeypatch.setenv("STEAM_API_KEY", "")
    monkeypatch.setenv("STEAM_ID", "")
    set_master_password_override("test-passphrase-for-unit-tests")
    yield
    set_master_password_override(None)
    sf = _secrets_file()
    if sf.exists():
        sf.unlink()


def test_stored_credentials_roundtrip() -> None:
    mark_connected(
        "steam",
        {"STEAM_API_KEY": "abc123", "STEAM_ID": "76561198000000000"},
    )
    creds = get_credentials("steam")
    assert creds["STEAM_API_KEY"] == "abc123"
    assert resolve_env("STEAM_API_KEY", provider="steam") == "abc123"


def test_api_providers_auth_kind() -> None:
    for key in ("steam", "xbox"):
        assert spec_for(key).kind == "browser"
        assert spec_for(key).login_url
    for key in ("itch", "itad"):
        assert spec_for(key).kind == "manual"
        assert spec_for(key).login_url


def test_env_fallback_when_store_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    from shared.profile_paths import DEFAULT_PROFILE_ID

    monkeypatch.setenv("BAKLOG_PROFILE", DEFAULT_PROFILE_ID)
    monkeypatch.setenv("ITAD_API_KEY", "from-env")
    assert resolve_env("ITAD_API_KEY", provider="itad") == "from-env"


def test_mark_connected_and_disconnect() -> None:
    mark_connected("nintendo", {"NINTENDO_COOKIE": "session=1"})
    assert get_credentials("nintendo")["NINTENDO_COOKIE"] == "session=1"
    disconnect("nintendo")
    doc = load_doc()
    assert "nintendo" not in doc.get("providers", {})


def test_gog_and_battlenet_connect_blob_used_by_resolve_env() -> None:
    """Connect saves cookie creds to the blob; fetchers read via resolve_env(provider=...)."""
    mark_connected("gog", {"GOG_AL": "gog-session-token"})
    assert get_credentials("gog")["GOG_AL"] == "gog-session-token"
    assert resolve_env("GOG_AL", provider="gog") == "gog-session-token"
    mark_connected("battlenet", {"BATTLENET_COOKIE": "cookie=blizzard"})
    assert get_credentials("battlenet")["BATTLENET_COOKIE"] == "cookie=blizzard"
    assert resolve_env("BATTLENET_COOKIE", provider="battlenet") == "cookie=blizzard"
