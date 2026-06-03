"""Concurrent profile credential reads do not cross-contaminate."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

import auth.secrets as secrets_mod
from auth.manager import profile_credentials_env
from auth.secrets import set_master_password_override, set_provider_blob
from shared import profile_paths
from shared.profiles import create_profile


@pytest.fixture()
def isolated_profiles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prof = tmp_path / "profiles"
    (prof / "default").mkdir(parents=True)
    monkeypatch.setattr(profile_paths, "ROOT", tmp_path)
    monkeypatch.setattr(profile_paths, "PROFILES_DIR", prof)
    monkeypatch.setattr(profile_paths, "INDEX_FILE", prof / "index.json")
    monkeypatch.delenv("BAKLOG_PROFILE", raising=False)
    set_master_password_override("test-passphrase-thread")
    secrets_mod._cache = None
    yield
    set_master_password_override(None)
    secrets_mod._cache = None


def _write_blob(profile_id: str, key: str) -> None:
    target = profile_paths.auth_dir(profile_id=profile_id)
    saved = (
        secrets_mod.AUTH_DIR,
        secrets_mod.SECRETS_FILE,
        secrets_mod.MASTER_KEY_FILE,
        secrets_mod._cache,
    )
    secrets_mod.AUTH_DIR = target
    secrets_mod.SECRETS_FILE = target / "secrets.bin"
    secrets_mod.MASTER_KEY_FILE = target / ".master_key"
    secrets_mod._cache = None
    try:
        set_provider_blob(
            "steam",
            {"STEAM_API_KEY": key, "STEAM_ID": "1", "status": "connected"},
        )
    finally:
        secrets_mod.AUTH_DIR, secrets_mod.SECRETS_FILE, secrets_mod.MASTER_KEY_FILE, secrets_mod._cache = (
            saved
        )


def test_concurrent_profile_credentials_env_isolation(
    isolated_profiles: None,
) -> None:
    create_profile("Work")
    _write_blob("default", "default-key")
    _write_blob("work", "work-key")

    results: dict[str, str | None] = {}
    errors: list[BaseException] = []

    def read(profile_id: str) -> None:
        try:
            env = profile_credentials_env(profile_id)
            results[profile_id] = env.get("STEAM_API_KEY")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [
        threading.Thread(target=read, args=("default",)),
        threading.Thread(target=read, args=("work",)),
        threading.Thread(target=read, args=("default",)),
        threading.Thread(target=read, args=("work",)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors
    assert results["default"] == "default-key"
    assert results["work"] == "work-key"
