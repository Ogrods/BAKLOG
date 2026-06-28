from __future__ import annotations
import os
import sys
import time
from pathlib import Path
import pytest
from shared import install_paths

def _reset_frozen_cache() -> None:
    install_paths._FROZEN_DATA_ROOT = None
    install_paths._FROZEN_MIGRATION_ATTEMPTED = False

def test_dev_roots_align(monkeypatch):
    monkeypatch.delenv('BAKLOG_DATA_DIR', raising=False)
    monkeypatch.setattr(install_paths, 'is_frozen', lambda: False)
    root = Path(__file__).resolve().parents[1]
    assert install_paths.bundle_root() == root
    assert install_paths.data_root() == root
    assert install_paths.static_root() == root

def test_data_dir_override(monkeypatch, tmp_path):
    monkeypatch.setenv('BAKLOG_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(install_paths, 'is_frozen', lambda: False)
    assert install_paths.data_root() == tmp_path.resolve()

def test_runtime_label_dev(monkeypatch):
    monkeypatch.setattr(install_paths, 'is_frozen', lambda: False)
    assert install_paths.runtime_label() == 'dev'

def test_runtime_label_installed(monkeypatch, tmp_path):
    app_dir = tmp_path / 'app'
    app_dir.mkdir()
    (app_dir / 'BAKLOG.exe').write_text('exe', encoding='utf-8')
    monkeypatch.setattr(install_paths, 'is_frozen', lambda: True)
    monkeypatch.setattr(install_paths, 'is_portable_frozen', lambda: False)
    assert install_paths.runtime_label() == 'installed'

def test_runtime_label_portable(monkeypatch, tmp_path):
    app_dir = tmp_path / 'app'
    app_dir.mkdir()
    (app_dir / 'BAKLOG.exe').write_text('exe', encoding='utf-8')
    monkeypatch.setattr(install_paths, 'is_frozen', lambda: True)
    monkeypatch.setattr(install_paths, 'is_portable_frozen', lambda: True)
    assert install_paths.runtime_label() == 'portable'

def test_serve_built_false_without_manifest(monkeypatch, tmp_path):
    monkeypatch.delenv('BAKLOG_SERVE_BUILT', raising=False)
    monkeypatch.setattr(install_paths, 'is_frozen', lambda: False)
    monkeypatch.setattr(install_paths, 'bundle_root', lambda: tmp_path)
    install_paths._BUILT_MANIFEST_CACHE = None
    install_paths._BUILT_MANIFEST_MTIME_NS = None
    assert install_paths.serve_built_frontend() is False
    assert install_paths.load_built_manifest() == {}

def test_manifest_cache_invalidates_on_mtime_change(monkeypatch, tmp_path):
    dist = tmp_path / 'dist'
    dist.mkdir()
    manifest = dist / 'manifest.json'
    manifest.write_text('{"js/app.js":"js/app-OLD.js"}', encoding='utf-8')
    monkeypatch.setenv('BAKLOG_SERVE_BUILT', '1')
    monkeypatch.setattr(install_paths, 'is_frozen', lambda: False)
    monkeypatch.setattr(install_paths, 'bundle_root', lambda: tmp_path)
    install_paths._BUILT_MANIFEST_CACHE = None
    install_paths._BUILT_MANIFEST_MTIME_NS = None
    assert install_paths.load_built_manifest()['js/app.js'] == 'js/app-OLD.js'
    manifest.write_text('{"js/app.js":"js/app-NEW.js"}', encoding='utf-8')
    os.utime(manifest, (time.time() + 1, time.time() + 1))
    assert install_paths.load_built_manifest()['js/app.js'] == 'js/app-NEW.js'

def test_serve_built_true_with_flag_and_manifest(monkeypatch, tmp_path):
    dist = tmp_path / 'dist'
    dist.mkdir()
    (dist / 'manifest.json').write_text('{"app.css":"app.abc.css","js/app.js":"js/app-XYZ.js","js/chunks":[]}', encoding='utf-8')
    monkeypatch.setenv('BAKLOG_SERVE_BUILT', '1')
    monkeypatch.setattr(install_paths, 'is_frozen', lambda: False)
    monkeypatch.setattr(install_paths, 'bundle_root', lambda: tmp_path)
    install_paths._BUILT_MANIFEST_CACHE = None
    install_paths._BUILT_MANIFEST_MTIME_NS = None
    assert install_paths.serve_built_frontend() is True
    manifest = install_paths.load_built_manifest()
    assert manifest['app.css'] == 'app.abc.css'
    assets = install_paths.built_immutable_assets()
    assert 'app.abc.css' in assets
    assert 'js/app-XYZ.js' in assets

def test_frozen_bundle_paths(monkeypatch, tmp_path):
    tray_exe = tmp_path / 'BAKLOG Tray.exe'
    server_exe = tmp_path / 'BAKLOG.exe'
    tray_exe.write_text('tray', encoding='utf-8')
    server_exe.write_text('server', encoding='utf-8')
    monkeypatch.setattr(install_paths, 'is_frozen', lambda: True)
    monkeypatch.setattr(install_paths.sys, 'executable', str(tray_exe))
    assert install_paths.frozen_bundle_dir() == tmp_path.resolve()
    assert install_paths.frozen_server_exe() == server_exe
    assert install_paths.frozen_tray_exe() == tray_exe

@pytest.mark.skipif(sys.platform != 'win32', reason='Windows LOCALAPPDATA frozen data dir')
def test_frozen_default_data_dir_windows(monkeypatch, tmp_path):
    _reset_frozen_cache()
    monkeypatch.delenv('BAKLOG_DATA_DIR', raising=False)
    monkeypatch.delenv('BAKLOG_PORTABLE', raising=False)
    app_dir = tmp_path / 'app'
    app_dir.mkdir()
    data_dir = tmp_path / 'BAKLOG-Data'
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    monkeypatch.setattr(install_paths, 'is_frozen', lambda: True)
    monkeypatch.setattr(install_paths.sys, 'executable', str(app_dir / 'BAKLOG.exe'))
    (app_dir / 'BAKLOG.exe').write_text('exe', encoding='utf-8')
    assert install_paths.data_root() == data_dir.resolve()

def test_frozen_portable_marker_uses_install_dir(monkeypatch, tmp_path):
    _reset_frozen_cache()
    monkeypatch.delenv('BAKLOG_DATA_DIR', raising=False)
    monkeypatch.delenv('BAKLOG_PORTABLE', raising=False)
    app_dir = tmp_path / 'app'
    app_dir.mkdir()
    (app_dir / 'BAKLOG.exe').write_text('exe', encoding='utf-8')
    (app_dir / install_paths.PORTABLE_MARKER).write_text('', encoding='utf-8')
    monkeypatch.setattr(install_paths, 'is_frozen', lambda: True)
    monkeypatch.setattr(install_paths.sys, 'executable', str(app_dir / 'BAKLOG.exe'))
    assert install_paths.data_root() == app_dir.resolve()
    assert install_paths.resolved_data_dir_for_uninstall() == app_dir.resolve()

@pytest.mark.skipif(sys.platform != 'win32', reason='Windows LOCALAPPDATA frozen data dir')
def test_resolved_data_dir_for_uninstall_default_windows(monkeypatch, tmp_path):
    monkeypatch.delenv('BAKLOG_DATA_DIR', raising=False)
    monkeypatch.delenv('BAKLOG_PORTABLE', raising=False)
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    app_dir = tmp_path / 'app'
    app_dir.mkdir()
    (app_dir / 'BAKLOG.exe').write_text('exe', encoding='utf-8')
    monkeypatch.setattr(install_paths, 'is_frozen', lambda: True)
    monkeypatch.setattr(install_paths.sys, 'executable', str(app_dir / 'BAKLOG.exe'))
    assert install_paths.resolved_data_dir_for_uninstall() == (tmp_path / 'BAKLOG-Data').resolve()

@pytest.mark.skipif(sys.platform != 'win32', reason='Windows LOCALAPPDATA frozen data dir')
def test_frozen_migrates_legacy_on_first_data_root(monkeypatch, tmp_path):
    _reset_frozen_cache()
    monkeypatch.delenv('BAKLOG_DATA_DIR', raising=False)
    monkeypatch.delenv('BAKLOG_PORTABLE', raising=False)
    app_dir = tmp_path / 'app'
    app_dir.mkdir()
    (app_dir / 'BAKLOG.exe').write_text('exe', encoding='utf-8')
    (app_dir / 'profiles').mkdir()
    (app_dir / 'profiles' / 'index.json').write_text('{"active":"default"}', encoding='utf-8')
    data_dir = tmp_path / 'BAKLOG-Data'
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    monkeypatch.setattr(install_paths, 'is_frozen', lambda: True)
    monkeypatch.setattr(install_paths.sys, 'executable', str(app_dir / 'BAKLOG.exe'))
    assert install_paths.data_root() == data_dir.resolve()
    assert (data_dir / 'profiles' / 'index.json').is_file()
    assert not (app_dir / 'profiles').exists()

def test_frozen_migrates_legacy_when_data_dir_override_set(monkeypatch, tmp_path):
    _reset_frozen_cache()
    monkeypatch.delenv('BAKLOG_PORTABLE', raising=False)
    app_dir = tmp_path / 'app'
    app_dir.mkdir()
    (app_dir / 'BAKLOG.exe').write_text('exe', encoding='utf-8')
    (app_dir / 'games_steam.json').write_text('{"games":[]}', encoding='utf-8')
    custom_data = tmp_path / 'custom-data'
    monkeypatch.setenv('BAKLOG_DATA_DIR', str(custom_data))
    monkeypatch.setattr(install_paths, 'is_frozen', lambda: True)
    monkeypatch.setattr(install_paths.sys, 'executable', str(app_dir / 'BAKLOG.exe'))
    assert install_paths.data_root() == custom_data.resolve()
    assert (custom_data / 'games_steam.json').is_file()
    assert not (app_dir / 'games_steam.json').exists()

@pytest.mark.skipif(sys.platform != 'win32', reason='Windows LOCALAPPDATA frozen data dir')
def test_frozen_syncs_bundled_auth_env_when_data_dir_missing_keys(monkeypatch, tmp_path):
    _reset_frozen_cache()
    monkeypatch.delenv('BAKLOG_DATA_DIR', raising=False)
    monkeypatch.delenv('BAKLOG_PORTABLE', raising=False)
    app_dir = tmp_path / 'BAKLOG'
    app_dir.mkdir()
    data_dir = tmp_path / 'BAKLOG-Data'
    data_dir.mkdir()
    prof = data_dir / 'profiles'
    prof.mkdir()
    (prof / 'index.json').write_text('{"active":"default","profiles":[]}', encoding='utf-8')
    (data_dir / '.legacy_migration_done').write_text('{}', encoding='utf-8')
    (app_dir / 'BAKLOG.exe').write_text('exe', encoding='utf-8')
    (app_dir / '.env').write_text('BAKLOG_SUPABASE_URL=https://proj.supabase.co\nBAKLOG_SUPABASE_ANON_KEY=anon-key\nBAKLOG_SUPABASE_JWT_SECRET=jwt-secret\n', encoding='utf-8')
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    monkeypatch.setattr(install_paths, 'is_frozen', lambda: True)
    monkeypatch.setattr(install_paths.sys, 'executable', str(app_dir / 'BAKLOG.exe'))
    assert install_paths.data_root() == data_dir.resolve()
    merged = (data_dir / '.env').read_text(encoding='utf-8')
    assert 'BAKLOG_SUPABASE_URL=https://proj.supabase.co' in merged
    assert 'BAKLOG_SUPABASE_JWT_SECRET' not in merged
    from shared.bundled_auth_env import apply_install_dir_auth_env
    apply_install_dir_auth_env()
    assert os.environ.get('BAKLOG_SUPABASE_JWT_SECRET') == 'jwt-secret'