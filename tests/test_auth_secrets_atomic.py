from __future__ import annotations
from pathlib import Path
import pytest
from auth.secrets import SecretsCorruptError, _secrets_file, load_doc, reset_secrets_store, save_doc, secrets_store_corrupt, set_master_password_override

@pytest.fixture(autouse=True)
def _isolated_auth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    auth_dir = tmp_path / 'auth'
    monkeypatch.setattr('auth.secrets.AUTH_DIR', auth_dir)
    monkeypatch.setattr('auth.secrets.SECRETS_FILE', auth_dir / 'secrets.bin')
    monkeypatch.setattr('auth.secrets.MASTER_KEY_FILE', auth_dir / '.master_key')
    set_master_password_override('test-passphrase-for-unit-tests')
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
    path.write_bytes(b'not-valid-ciphertext')
    with pytest.raises(SecretsCorruptError):
        load_doc()

def test_atomic_save_keeps_backup_on_replace() -> None:
    save_doc({'providers': {'steam': {'x': 1}}, 'settings': {'master_password_enabled': True}})
    path = _secrets_file()
    assert path.exists()
    first = path.read_bytes()
    save_doc({'providers': {'steam': {'x': 2}}, 'settings': {'master_password_enabled': True}})
    bak = path.with_suffix(path.suffix + '.bak')
    assert bak.exists()
    assert bak.read_bytes() == first
    doc = load_doc()
    assert doc['providers']['steam']['x'] == 2

def test_reset_secrets_store_archives_corrupt_blob() -> None:
    path = _secrets_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'not-valid-ciphertext')
    assert secrets_store_corrupt() is True
    reset_secrets_store()
    assert not path.exists()
    assert secrets_store_corrupt() is False
    archived = list(path.parent.glob('secrets.bin.corrupt-*'))
    assert len(archived) == 1
    assert archived[0].read_bytes() == b'not-valid-ciphertext'
    doc = load_doc()
    assert doc['providers'] == {}

def test_master_key_prefers_file_key_when_keyring_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    import auth.secrets as mod
    set_master_password_override(None)
    mod._cache = None
    mod._ensure_dir()
    file_key = b'\x01' * 32
    mod._write_master_key_file(file_key)
    monkeypatch.setattr('auth.secrets._load_keyring_key', lambda: b'\x02' * 32)
    monkeypatch.setattr('auth.secrets._save_keyring_key', lambda key: True)
    save_doc({'providers': {'steam': {'token': 'abc'}}, 'settings': {}})
    mod._cache = None
    doc = load_doc()
    assert doc['providers']['steam']['token'] == 'abc'
    set_master_password_override('test-passphrase-for-unit-tests')