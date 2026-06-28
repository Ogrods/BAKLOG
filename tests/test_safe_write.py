from __future__ import annotations
import time
from pathlib import Path
import pytest
from shared.safe_write import atomic_write_text, rotate_backup, safe_write_text

def test_atomic_write_creates_file(tmp_path: Path) -> None:
    target = tmp_path / 'out.json'
    atomic_write_text(target, '{"hello": "world"}')
    assert target.read_text(encoding='utf-8') == '{"hello": "world"}'

def test_atomic_write_replaces_existing(tmp_path: Path) -> None:
    target = tmp_path / 'out.json'
    target.write_text('old', encoding='utf-8')
    atomic_write_text(target, 'new')
    assert target.read_text(encoding='utf-8') == 'new'

def test_atomic_write_cleans_up_tmp_on_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / 'out.json'
    import os

    def fail_replace(*_a, **_kw):
        raise OSError('boom')
    monkeypatch.setattr(os, 'replace', fail_replace)
    with pytest.raises(OSError, match='boom'):
        atomic_write_text(target, 'payload')
    assert not target.exists()
    assert not (tmp_path / 'out.json.tmp').exists()

def test_rotate_backup_noop_when_no_source(tmp_path: Path) -> None:
    source = tmp_path / 'missing.json'
    backup_dir = tmp_path / 'backups'
    result = rotate_backup(source, backup_dir=backup_dir)
    assert result is None
    assert not backup_dir.exists()

def test_rotate_backup_copies_existing_file(tmp_path: Path) -> None:
    source = tmp_path / 'games_steam.json'
    source.write_text('{"games": [1, 2, 3]}', encoding='utf-8')
    backup_dir = tmp_path / 'backups' / 'games_steam'
    backup_path = rotate_backup(source, backup_dir=backup_dir)
    assert backup_path is not None
    assert backup_path.parent == backup_dir
    assert backup_path.name.startswith('games_steam-')
    assert backup_path.name.endswith('.json')
    assert backup_path.read_text(encoding='utf-8') == '{"games": [1, 2, 3]}'

def test_rotate_backup_prunes_to_keep_count(tmp_path: Path) -> None:
    source = tmp_path / 'games_steam.json'
    backup_dir = tmp_path / 'backups' / 'games_steam'
    for i in range(7):
        source.write_text(f'payload-{i}', encoding='utf-8')
        rotate_backup(source, backup_dir=backup_dir, keep=3)
        time.sleep(0.002)
    remaining = sorted(backup_dir.glob('games_steam-*.json'))
    assert len(remaining) == 3
    assert remaining[-1].read_text(encoding='utf-8') == 'payload-6'

def test_safe_write_text_first_write_no_backup(tmp_path: Path) -> None:
    target = tmp_path / 'out.json'
    backup_dir = tmp_path / 'backups'
    backup_path = safe_write_text(target, 'v1', backup_dir=backup_dir)
    assert backup_path is None
    assert target.read_text(encoding='utf-8') == 'v1'
    assert not backup_dir.exists()

def test_safe_write_text_second_write_creates_backup(tmp_path: Path) -> None:
    target = tmp_path / 'out.json'
    backup_dir = tmp_path / 'backups'
    safe_write_text(target, 'v1', backup_dir=backup_dir, prefix='out')
    backup_path = safe_write_text(target, 'v2', backup_dir=backup_dir, prefix='out')
    assert backup_path is not None
    assert backup_path.read_text(encoding='utf-8') == 'v1'
    assert target.read_text(encoding='utf-8') == 'v2'

def test_safe_write_uses_path_stem_as_default_prefix(tmp_path: Path) -> None:
    target = tmp_path / 'games_psn.json'
    backup_dir = tmp_path / 'backups'
    target.write_text('seed', encoding='utf-8')
    backup_path = safe_write_text(target, 'fresh', backup_dir=backup_dir)
    assert backup_path is not None
    assert backup_path.name.startswith('games_psn-')