from __future__ import annotations
from pathlib import Path
import pytest
from auth.secrets import get_provider_blob, reset_cache, set_master_password_override
from clients.epic_client import EpicClient, default_epic_cache_dir
from shared import profile_paths
from shared.profiles import create_profile

@pytest.fixture()
def isolated_profiles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prof = tmp_path / 'profiles'
    (prof / 'default').mkdir(parents=True)
    monkeypatch.setattr(profile_paths, 'ROOT', tmp_path)
    monkeypatch.setattr(profile_paths, 'PROFILES_DIR', prof)
    monkeypatch.setattr(profile_paths, 'INDEX_FILE', prof / 'index.json')
    monkeypatch.delenv('BAKLOG_PROFILE', raising=False)
    reset_cache()
    set_master_password_override('test-passphrase-for-unit-tests')
    yield
    set_master_password_override(None)
    reset_cache()

def test_epic_session_stored_in_secrets_not_plaintext(isolated_profiles: None, monkeypatch: pytest.MonkeyPatch) -> None:
    create_profile('Work')
    monkeypatch.setenv('BAKLOG_PROFILE', 'work')
    reset_cache()
    cache_dir = default_epic_cache_dir()
    assert cache_dir == profile_paths.epic_cache_dir(profile_id='work')
    client = EpicClient(cache_dir=cache_dir)
    client._access_token = 'access'
    client._refresh_token = 'refresh'
    client._account_id = 'acct'
    client._save_session()
    assert not (cache_dir / 'session.json').is_file()
    assert not (profile_paths.ROOT / 'cache' / 'epic' / 'session.json').is_file()
    blob = get_provider_blob('epic_session')
    assert blob.get('refresh_token') == 'refresh'
    assert blob.get('account_id') == 'acct'
    reset_cache()
    loaded = EpicClient(cache_dir=cache_dir)._load_session()
    assert loaded is not None
    assert loaded.get('refresh_token') == 'refresh'

def test_epic_migrates_plaintext_session_into_secrets(isolated_profiles: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    create_profile('Work')
    monkeypatch.setenv('BAKLOG_PROFILE', 'work')
    reset_cache()
    legacy_dir = tmp_path / 'cache' / 'epic'
    legacy_dir.mkdir(parents=True)
    (legacy_dir / 'session.json').write_text('{"refresh_token": "old", "account_id": "1"}', encoding='utf-8')
    cache_dir = default_epic_cache_dir()
    profile_session = cache_dir / 'session.json'
    if profile_session.exists():
        profile_session.unlink()
    client = EpicClient(cache_dir=cache_dir)
    loaded = client._load_session()
    assert loaded is not None
    assert loaded.get('refresh_token') == 'old'
    assert get_provider_blob('epic_session').get('refresh_token') == 'old'
    assert not profile_session.is_file()
    assert not (legacy_dir / 'session.json').is_file()