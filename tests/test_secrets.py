import os

import pytest

from auth import secrets as secrets_mod


@pytest.fixture()
def isolated_auth(tmp_path, monkeypatch):
    monkeypatch.setattr(secrets_mod, "AUTH_DIR", tmp_path)
    monkeypatch.setattr(secrets_mod, "SECRETS_FILE", tmp_path / "secrets.bin")
    monkeypatch.setattr(secrets_mod, "MASTER_KEY_FILE", tmp_path / ".master_key")
    monkeypatch.setattr(secrets_mod, "PROFILE_ID_OVERRIDE", "test-profile")
    secrets_mod.reset_cache()
    secrets_mod.set_master_password_override(None)
    secrets_mod._warned_plaintext_master_key = False
    yield tmp_path
    secrets_mod.reset_cache()
    secrets_mod.set_master_password_override(None)


def _force_no_keyring(monkeypatch):
    monkeypatch.setattr(secrets_mod, "_load_keyring_key", lambda: None)
    monkeypatch.setattr(secrets_mod, "_save_keyring_key", lambda key: False)


def test_master_key_written_to_disk_when_keyring_unavailable(isolated_auth, monkeypatch):
    _force_no_keyring(monkeypatch)
    key = secrets_mod._get_master_key()
    assert len(key) == 32
    mk = secrets_mod._master_key_file()
    assert mk.exists()
    assert secrets_mod._read_master_key_file() == key


def test_keyring_success_does_not_write_disk(isolated_auth, monkeypatch):
    saved = {}
    monkeypatch.setattr(secrets_mod, "_load_keyring_key", lambda: None)

    def fake_save(key):
        saved["key"] = key
        return True

    monkeypatch.setattr(secrets_mod, "_save_keyring_key", fake_save)
    key = secrets_mod._get_master_key()
    assert saved["key"] == key
    assert not secrets_mod._master_key_file().exists()


def test_legacy_plaintext_master_key_is_readable(isolated_auth, monkeypatch):
    _force_no_keyring(monkeypatch)
    raw_key = b"x" * 32
    secrets_mod._master_key_file().write_bytes(raw_key)
    assert secrets_mod._get_master_key() == raw_key


def test_provider_blob_round_trip_with_disk_key(isolated_auth, monkeypatch):
    _force_no_keyring(monkeypatch)
    secrets_mod.set_provider_blob("steam", {"token": "abc", "n": 1})
    secrets_mod.reset_cache()
    assert secrets_mod.get_provider_blob("steam") == {"token": "abc", "n": 1}


@pytest.mark.skipif(os.name != "nt", reason="DPAPI is Windows-only")
def test_dpapi_round_trip():
    data = b"super-secret-master-key-bytes!!!"
    protected = secrets_mod._dpapi_protect(data)
    assert protected is not None
    assert protected != data
    assert secrets_mod._dpapi_unprotect(protected) == data


@pytest.mark.skipif(os.name != "nt", reason="DPAPI is Windows-only")
def test_master_key_file_is_dpapi_protected_on_windows(isolated_auth, monkeypatch):
    _force_no_keyring(monkeypatch)
    key = secrets_mod._get_master_key()
    raw = secrets_mod._master_key_file().read_bytes()
    assert raw.startswith(secrets_mod._DPAPI_MAGIC)
    assert key not in raw


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_master_key_file_permissions_are_owner_only(isolated_auth, monkeypatch):
    _force_no_keyring(monkeypatch)
    secrets_mod._get_master_key()
    mode = secrets_mod._master_key_file().stat().st_mode & 511
    assert mode == 384
