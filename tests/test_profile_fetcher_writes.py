from __future__ import annotations
import json
from pathlib import Path
import pytest
from fetchers._base import write_catalog_text
from shared import profile_paths

@pytest.fixture
def isolated_profiles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    prof_dir = tmp_path / 'profiles'
    monkeypatch.setattr(profile_paths, 'ROOT', tmp_path)
    monkeypatch.setattr(profile_paths, 'PROFILES_DIR', prof_dir)
    monkeypatch.setattr(profile_paths, 'INDEX_FILE', prof_dir / 'index.json')
    monkeypatch.delenv('BAKLOG_PROFILE', raising=False)
    return tmp_path

def test_write_catalog_text_scoped_profile(isolated_profiles: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    work = isolated_profiles / 'profiles' / 'work'
    work.mkdir(parents=True)
    index = {'active': 'work', 'profiles': [{'id': 'default', 'label': 'Default', 'created_at': 't'}, {'id': 'work', 'label': 'Work', 'created_at': 't'}]}
    (isolated_profiles / 'profiles' / 'index.json').write_text(json.dumps(index), encoding='utf-8')
    monkeypatch.setenv('BAKLOG_PROFILE', 'work')
    rel = Path('games_steam.json')
    payload = json.dumps({'game_count': 0, 'games': []})
    disk = write_catalog_text(rel, payload)
    assert disk == work / 'games_steam.json'
    assert disk.is_file()
    assert not (isolated_profiles / 'games_steam.json').exists()

def test_invalid_profile_id_rejected(isolated_profiles: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('BAKLOG_PROFILE', '../escape')
    assert profile_paths.get_active_profile_id() == 'default'