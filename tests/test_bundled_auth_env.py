"""Tests for shared.bundled_auth_env."""

from __future__ import annotations

from pathlib import Path

from shared.bundled_auth_env import (
    apply_install_dir_auth_env,
    parse_env_file,
    sync_bundled_auth_env_to_data_dir,
)


def test_sync_fills_missing_auth_keys_when_data_env_absent(tmp_path: Path) -> None:
    install = tmp_path / "install"
    data = tmp_path / "data"
    install.mkdir()
    (install / ".env").write_text(
        "BAKLOG_SUPABASE_URL=https://proj.supabase.co\n"
        "BAKLOG_SUPABASE_ANON_KEY=anon-key\n"
        "BAKLOG_SUPABASE_JWT_SECRET=jwt-secret\n",
        encoding="utf-8",
    )
    assert sync_bundled_auth_env_to_data_dir(install, data) is True
    merged = parse_env_file(data / ".env")
    assert merged["BAKLOG_SUPABASE_URL"] == "https://proj.supabase.co"
    assert merged["BAKLOG_SUPABASE_ANON_KEY"] == "anon-key"
    assert merged["BAKLOG_SUPABASE_JWT_SECRET"] == "jwt-secret"


def test_sync_skips_when_data_env_already_has_auth_keys(tmp_path: Path) -> None:
    install = tmp_path / "install"
    data = tmp_path / "data"
    install.mkdir()
    data.mkdir()
    (install / ".env").write_text(
        "BAKLOG_SUPABASE_URL=https://new.supabase.co\nBAKLOG_SUPABASE_ANON_KEY=new-anon\n",
        encoding="utf-8",
    )
    (data / ".env").write_text(
        "BAKLOG_SUPABASE_URL=https://old.supabase.co\nBAKLOG_SUPABASE_ANON_KEY=old-anon\n",
        encoding="utf-8",
    )
    assert sync_bundled_auth_env_to_data_dir(install, data) is False
    assert parse_env_file(data / ".env")["BAKLOG_SUPABASE_URL"] == "https://old.supabase.co"


def test_sync_fills_only_missing_jwt_secret(tmp_path: Path, monkeypatch) -> None:
    install = tmp_path / "install"
    data = tmp_path / "data"
    install.mkdir()
    data.mkdir()
    (install / ".env").write_text(
        "BAKLOG_SUPABASE_URL=https://proj.supabase.co\n"
        "BAKLOG_SUPABASE_ANON_KEY=anon-key\n"
        "BAKLOG_SUPABASE_JWT_SECRET=jwt-secret\n",
        encoding="utf-8",
    )
    (data / ".env").write_text(
        "BAKLOG_SUPABASE_URL=https://proj.supabase.co\nBAKLOG_SUPABASE_ANON_KEY=anon-key\n",
        encoding="utf-8",
    )
    assert sync_bundled_auth_env_to_data_dir(install, data) is True
    merged = parse_env_file(data / ".env")
    assert merged["BAKLOG_SUPABASE_JWT_SECRET"] == "jwt-secret"


def test_apply_install_dir_auth_env_uses_bundle_when_env_empty(
    tmp_path: Path, monkeypatch
) -> None:
    install = tmp_path / "install"
    install.mkdir()
    (install / ".env").write_text(
        "BAKLOG_SUPABASE_URL=https://proj.supabase.co\nBAKLOG_SUPABASE_ANON_KEY=anon-key\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("BAKLOG_SUPABASE_URL", raising=False)
    monkeypatch.delenv("BAKLOG_SUPABASE_ANON_KEY", raising=False)
    monkeypatch.setattr("shared.install_paths.is_frozen", lambda: True)
    monkeypatch.setattr("shared.install_paths.frozen_bundle_dir", lambda: install)
    apply_install_dir_auth_env()
    import os

    assert os.environ["BAKLOG_SUPABASE_URL"] == "https://proj.supabase.co"
    assert os.environ["BAKLOG_SUPABASE_ANON_KEY"] == "anon-key"
