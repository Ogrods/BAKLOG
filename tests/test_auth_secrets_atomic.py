"""Atomic secrets.bin writes and corrupt-load protection."""

from __future__ import annotations

from pathlib import Path

import pytest

from auth.secrets import SecretsCorruptError, load_doc, save_doc, set_master_password_override
from auth.secrets import _secrets_file


@pytest.fixture(autouse=True)
def _isolated_auth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    auth_dir = tmp_path / "auth"
    monkeypatch.setattr("auth.secrets.AUTH_DIR", auth_dir)
    monkeypatch.setattr("auth.secrets.SECRETS_FILE", auth_dir / "secrets.bin")
    monkeypatch.setattr("auth.secrets.MASTER_KEY_FILE", auth_dir / ".master_key")
    set_master_password_override("test-passphrase-for-unit-tests")
    import auth.secrets as mod

    mod._cache = None
    yield
    set_master_password_override(None)
    mod._cache = None


def test_corrupt_secrets_raises_not_empty() -> None:
    import auth.secrets as mod

    mod._cache = None
    path = _secrets_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not-valid-ciphertext")
    with pytest.raises(SecretsCorruptError):
        load_doc()


def test_atomic_save_keeps_backup_on_replace() -> None:
    save_doc({"providers": {"steam": {"x": 1}}, "settings": {"master_password_enabled": True}})
    path = _secrets_file()
    assert path.exists()
    first = path.read_bytes()
    save_doc({"providers": {"steam": {"x": 2}}, "settings": {"master_password_enabled": True}})
    bak = path.with_suffix(path.suffix + ".bak")
    assert bak.exists()
    assert bak.read_bytes() == first
    doc = load_doc()
    assert doc["providers"]["steam"]["x"] == 2
