"""Amazon Games launcher Disconnect/Connect (local provider disabled flag)."""

from __future__ import annotations

from pathlib import Path

import pytest

import auth.secrets as secrets
from auth.manager import (
    _provider_state,
    disconnect,
    enable_local,
    is_local_provider_disabled,
)
from auth.secrets import get_provider_blob, set_master_password_override, set_provider_blob
from shared import profile_paths


@pytest.fixture(autouse=True)
def isolated_default_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    prof_dir = tmp_path / "profiles"
    (prof_dir / "default").mkdir(parents=True)
    monkeypatch.setattr(profile_paths, "ROOT", tmp_path)
    monkeypatch.setattr(profile_paths, "PROFILES_DIR", prof_dir)
    monkeypatch.setattr(profile_paths, "INDEX_FILE", prof_dir / "index.json")
    monkeypatch.delenv("BAKLOG_PROFILE", raising=False)
    set_master_password_override("test-passphrase-amazon-disable")
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


def test_disconnect_local_sets_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("auth.manager.platform_supported", lambda platforms: True)
    disconnect("amazon")
    assert get_provider_blob("amazon").get("disabled") is True


def test_enable_local_clears_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("auth.manager.platform_supported", lambda platforms: True)
    set_provider_blob("amazon", {"disabled": True})
    enable_local("amazon")
    assert "disabled" not in get_provider_blob("amazon")


def test_enable_local_rejects_browser_provider() -> None:
    with pytest.raises(ValueError, match="not a local provider"):
        enable_local("steam")


def test_is_local_provider_disabled() -> None:
    set_provider_blob("amazon", {"disabled": True})
    assert is_local_provider_disabled("amazon") is True
    assert is_local_provider_disabled("steam") is False


def test_provider_state_local_respects_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("auth.manager.platform_supported", lambda platforms: True)
    sql = Path("/fake/amazon/sql")
    set_provider_blob("amazon", {"disabled": True, "AMAZON_GAMES_SQL_DIR": str(sql)})
    assert _provider_state("amazon") == "disconnected"


def test_provider_state_local_connected_when_sql_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("auth.manager.platform_supported", lambda platforms: True)
    sql_dir = tmp_path / "AmazonSql"
    sql_dir.mkdir()
    (sql_dir / "Entitlements.sqlite").write_bytes(b"")
    set_provider_blob("amazon", {"AMAZON_GAMES_SQL_DIR": str(sql_dir)})
    monkeypatch.setattr("auth.manager._env_fallback_allowed", lambda: True)
    assert _provider_state("amazon") == "connected"
