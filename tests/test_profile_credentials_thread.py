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
    secrets_mod.reset_cache()
    yield
    set_master_password_override(None)
    secrets_mod.reset_cache()


def _write_blob(profile_id: str, key: str) -> None:
    target = profile_paths.auth_dir(profile_id=profile_id)
    saved = (
        secrets_mod.AUTH_DIR,
        secrets_mod.SECRETS_FILE,
        secrets_mod.MASTER_KEY_FILE,
        secrets_mod._cache,
        secrets_mod._cache_key,
        secrets_mod.PROFILE_ID_OVERRIDE,
    )
    secrets_mod.AUTH_DIR = target
    secrets_mod.SECRETS_FILE = target / "secrets.bin"
    secrets_mod.MASTER_KEY_FILE = target / ".master_key"
    secrets_mod._cache = None
    secrets_mod._cache_key = None
    # Encrypt with this profile's HKDF subkey so the read path (which sets the
    # same override) can decrypt it; otherwise the blob is keyed to the active
    # profile and silently fails to decrypt.
    secrets_mod.PROFILE_ID_OVERRIDE = profile_id
    try:
        set_provider_blob(
            "steam",
            {"STEAM_API_KEY": key, "STEAM_ID": "1", "status": "connected"},
        )
    finally:
        (
            secrets_mod.AUTH_DIR,
            secrets_mod.SECRETS_FILE,
            secrets_mod.MASTER_KEY_FILE,
            secrets_mod._cache,
            secrets_mod._cache_key,
            secrets_mod.PROFILE_ID_OVERRIDE,
        ) = saved


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


def test_contextvar_profile_pin_does_not_reuse_foreign_cache(
    isolated_profiles: None,
) -> None:
    """JWT-style pins call load_doc without _with_profile_secrets."""
    from auth.secrets import get_provider_blob

    create_profile("Work")
    _write_blob("default", "default-key")
    _write_blob("work", "work-key")
    secrets_mod.reset_cache()

    tok_a = profile_paths.set_request_profile_id("default")
    try:
        assert get_provider_blob("steam").get("STEAM_API_KEY") == "default-key"
    finally:
        profile_paths.reset_request_profile_id(tok_a)

    tok_b = profile_paths.set_request_profile_id("work")
    try:
        assert get_provider_blob("steam").get("STEAM_API_KEY") == "work-key"
    finally:
        profile_paths.reset_request_profile_id(tok_b)


def test_contextvar_concurrent_pins_isolate_secrets(
    isolated_profiles: None,
) -> None:
    from auth.secrets import get_provider_blob

    create_profile("Work")
    _write_blob("default", "default-key")
    _write_blob("work", "work-key")
    secrets_mod.reset_cache()

    results: dict[str, list[str]] = {"default": [], "work": []}
    errors: list[BaseException] = []
    barrier = threading.Barrier(2)

    def reader(profile_id: str) -> None:
        try:
            tok = profile_paths.set_request_profile_id(profile_id)
            try:
                barrier.wait(timeout=5)
                for _ in range(40):
                    blob = get_provider_blob("steam") or {}
                    results[profile_id].append(str(blob.get("STEAM_API_KEY")))
            finally:
                profile_paths.reset_request_profile_id(tok)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [
        threading.Thread(target=reader, args=("default",)),
        threading.Thread(target=reader, args=("work",)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert not errors
    assert results["default"] and all(v == "default-key" for v in results["default"])
    assert results["work"] and all(v == "work-key" for v in results["work"])
