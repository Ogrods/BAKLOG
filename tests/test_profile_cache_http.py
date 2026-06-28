from __future__ import annotations
import json
import threading
import urllib.error
import urllib.request
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
import pytest
import server
from shared import profile_paths
from shared.profiles import create_profile, set_active_profile

@pytest.fixture()
def profile_cache_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    prof = tmp_path / 'profiles'
    monkeypatch.setattr(profile_paths, 'ROOT', tmp_path)
    monkeypatch.setattr(profile_paths, 'PROFILES_DIR', prof)
    monkeypatch.setattr(profile_paths, 'INDEX_FILE', prof / 'index.json')
    monkeypatch.setattr(server, 'ROOT', tmp_path)
    server._refresh_personal_paths()
    httpd = ThreadingHTTPServer(('127.0.0.1', 0), partial(server.Handler, directory=str(tmp_path)))
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{port}'
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)

def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=5) as resp:
        return json.loads(resp.read().decode('utf-8'))

def test_cache_json_served_from_active_profile_not_repo_root(profile_cache_server: str, tmp_path: Path) -> None:
    create_profile('Work')
    set_active_profile('work')
    server._refresh_personal_paths()
    root_cache = tmp_path / 'cache'
    root_cache.mkdir(parents=True, exist_ok=True)
    (root_cache / 'hltb_map.json').write_text(json.dumps({'fetched_at': 'root', 'marker': 'root'}), encoding='utf-8')
    work_cache = profile_paths.cache_json_path('hltb_map.json', profile_id='work')
    work_cache.parent.mkdir(parents=True, exist_ok=True)
    work_cache.write_text(json.dumps({'fetched_at': '2026-06-03T00:00:00+00:00', 'marker': 'work'}), encoding='utf-8')
    data = _get_json(f'{profile_cache_server}/cache/hltb_map.json')
    assert data.get('marker') == 'work'
    assert data.get('marker') != 'root'

def test_missing_profile_cache_returns_empty_stub_not_root_cache(profile_cache_server: str, tmp_path: Path) -> None:
    create_profile('Work')
    set_active_profile('work')
    server._refresh_personal_paths()
    root_cache = tmp_path / 'cache'
    root_cache.mkdir(parents=True, exist_ok=True)
    (root_cache / 'steam_review_map.json').write_text(json.dumps({'fetched_at': 'root', 'marker': 'root'}), encoding='utf-8')
    data = _get_json(f'{profile_cache_server}/cache/steam_review_map.json')
    assert data.get('fetched_at') is None
    assert data.get('marker') != 'root'

def test_missing_profile_cross_store_meta_stub_shape(profile_cache_server: str, tmp_path: Path) -> None:
    create_profile('Work')
    set_active_profile('work')
    server._refresh_personal_paths()
    data = _get_json(f'{profile_cache_server}/cache/cross_store_images_meta.json')
    assert data.get('fetched_at') is None
    assert data.get('no_steam_match') == []

def test_profiles_url_prefix_blocked(profile_cache_server: str, tmp_path: Path) -> None:
    create_profile('Work')
    set_active_profile('work')
    server._refresh_personal_paths()
    work_games = profile_paths.catalog_path('games_steam.json', profile_id='work')
    work_games.parent.mkdir(parents=True, exist_ok=True)
    work_games.write_text('{"games":[]}', encoding='utf-8')
    try:
        _get_json(f'{profile_cache_server}/profiles/work/games_steam.json')
        raised = None
    except urllib.error.HTTPError as exc:
        raised = exc.code
    assert raised == 404