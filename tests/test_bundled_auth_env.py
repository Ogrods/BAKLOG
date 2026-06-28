from __future__ import annotations
import os
from pathlib import Path
from shared.bundled_auth_env import apply_install_dir_auth_env, parse_env_file, sync_bundled_auth_env_to_data_dir

def test_sync_fills_missing_auth_keys_when_data_env_absent(tmp_path: Path) -> None:
    install = tmp_path / 'install'
    data = tmp_path / 'data'
    install.mkdir()
    (install / '.env').write_text('BAKLOG_SUPABASE_URL=https://proj.supabase.co\nBAKLOG_SUPABASE_ANON_KEY=anon-key\nBAKLOG_SUPABASE_JWT_SECRET=jwt-secret\n', encoding='utf-8')
    assert sync_bundled_auth_env_to_data_dir(install, data) is True
    merged = parse_env_file(data / '.env')
    assert merged['BAKLOG_SUPABASE_URL'] == 'https://proj.supabase.co'
    assert merged['BAKLOG_SUPABASE_ANON_KEY'] == 'anon-key'
    assert 'BAKLOG_SUPABASE_JWT_SECRET' not in merged

def test_sync_overwrites_stale_data_auth_keys(tmp_path: Path) -> None:
    install = tmp_path / 'install'
    data = tmp_path / 'data'
    install.mkdir()
    data.mkdir()
    (install / '.env').write_text('BAKLOG_SUPABASE_URL=https://new.supabase.co\nBAKLOG_SUPABASE_ANON_KEY=new-anon\n', encoding='utf-8')
    (data / '.env').write_text('BAKLOG_SUPABASE_URL=https://old.supabase.co\nBAKLOG_SUPABASE_ANON_KEY=old-anon\n', encoding='utf-8')
    assert sync_bundled_auth_env_to_data_dir(install, data) is True
    merged = parse_env_file(data / '.env')
    assert merged['BAKLOG_SUPABASE_URL'] == 'https://new.supabase.co'
    assert merged['BAKLOG_SUPABASE_ANON_KEY'] == 'new-anon'

def test_sync_does_not_copy_jwt_secret_to_data_dir(tmp_path: Path) -> None:
    install = tmp_path / 'install'
    data = tmp_path / 'data'
    install.mkdir()
    data.mkdir()
    (install / '.env').write_text('BAKLOG_SUPABASE_URL=https://proj.supabase.co\nBAKLOG_SUPABASE_ANON_KEY=anon-key\nBAKLOG_SUPABASE_JWT_SECRET=jwt-secret\n', encoding='utf-8')
    (data / '.env').write_text('BAKLOG_SUPABASE_URL=https://proj.supabase.co\nBAKLOG_SUPABASE_ANON_KEY=anon-key\n', encoding='utf-8')
    assert sync_bundled_auth_env_to_data_dir(install, data) is False
    merged = parse_env_file(data / '.env')
    assert 'BAKLOG_SUPABASE_JWT_SECRET' not in merged

def test_sync_strips_legacy_jwt_secret_from_data_env(tmp_path: Path) -> None:
    install = tmp_path / 'install'
    data = tmp_path / 'data'
    install.mkdir()
    data.mkdir()
    (install / '.env').write_text('BAKLOG_SUPABASE_URL=https://proj.supabase.co\nBAKLOG_SUPABASE_ANON_KEY=anon-key\n', encoding='utf-8')
    (data / '.env').write_text('BAKLOG_SUPABASE_URL=https://proj.supabase.co\nBAKLOG_SUPABASE_ANON_KEY=anon-key\nBAKLOG_SUPABASE_JWT_SECRET=legacy-jwt\n', encoding='utf-8')
    assert sync_bundled_auth_env_to_data_dir(install, data) is True
    merged = parse_env_file(data / '.env')
    assert 'BAKLOG_SUPABASE_JWT_SECRET' not in merged

def test_apply_install_dir_auth_env_overwrites_stale_process_env(tmp_path: Path, monkeypatch) -> None:
    install = tmp_path / 'install'
    install.mkdir()
    (install / '.env').write_text('BAKLOG_SUPABASE_URL=https://proj.supabase.co\nBAKLOG_SUPABASE_ANON_KEY=anon-key\n', encoding='utf-8')
    monkeypatch.setenv('BAKLOG_SUPABASE_URL', 'https://stale.supabase.co')
    monkeypatch.setenv('BAKLOG_SUPABASE_ANON_KEY', 'stale-anon')
    monkeypatch.setattr('shared.install_paths.is_frozen', lambda: True)
    monkeypatch.setattr('shared.install_paths.frozen_bundle_dir', lambda: install)
    apply_install_dir_auth_env()
    assert os.environ['BAKLOG_SUPABASE_URL'] == 'https://proj.supabase.co'
    assert os.environ['BAKLOG_SUPABASE_ANON_KEY'] == 'anon-key'