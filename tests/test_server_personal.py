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

@pytest.fixture()
def personal_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    prof = tmp_path / 'profiles'
    monkeypatch.setattr(profile_paths, 'ROOT', tmp_path)
    monkeypatch.setattr(profile_paths, 'PROFILES_DIR', prof)
    monkeypatch.setattr(profile_paths, 'INDEX_FILE', prof / 'index.json')
    server._refresh_personal_paths()
    httpd = ThreadingHTTPServer(('127.0.0.1', 0), partial(server.Handler, directory=str(server.ROOT)))
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{port}'
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)

def _request(base: str, method: str, path: str, body: dict | None=None, *, extra_headers: dict[str, str] | None=None) -> tuple[int, dict]:
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    if method != 'GET':
        headers[server._BAKLOG_LOCAL_HEADER] = '1'
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(f'{base}{path}', data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return (resp.status, json.loads(resp.read().decode('utf-8')))
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode('utf-8')
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            parsed = {'error': payload}
        return (exc.code, parsed)

def test_personal_restores_from_backup_on_corrupt_primary(personal_server: str, monkeypatch: pytest.MonkeyPatch) -> None:
    backup_dir = server.personal_backup_dir()
    backup_dir.mkdir(parents=True, exist_ok=True)
    good = {'personal': {'g1': {'status': 'backlog'}}, 'prefs': {}, 'manual': [], 'libraryFirstSeen': {}, 'updated_at': 1.0, 'schema_version': 1}
    (backup_dir / 'personal-20260101-120000.json').write_text(json.dumps(good), encoding='utf-8')
    path = server.personal_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{not json', encoding='utf-8')
    status, doc = _request(personal_server, 'GET', '/api/personal')
    assert status == 200
    assert doc['personal']['g1']['status'] == 'backlog'

def test_personal_corrupt_without_backup_returns_503(personal_server: str) -> None:
    path = server.personal_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{bad', encoding='utf-8')
    status, body = _request(personal_server, 'GET', '/api/personal')
    assert status == 503
    assert 'corrupt' in body.get('error', '').lower()

def test_personal_get_empty_doc(personal_server: str):
    status, doc = _request(personal_server, 'GET', '/api/personal')
    assert status == 200
    assert doc['personal'] == {}
    assert doc['prefs'] == {}
    assert doc['manual'] == []
    assert doc['libraryFirstSeen'] == {}
    assert doc['schema_version'] == 1

def test_personal_put_rejects_empty_overwrite_of_meaningful_doc(personal_server: str) -> None:
    seed = {'personal': {'steam:1': {'status': 'backlog'}}, 'prefs': {}, 'manual': [], 'libraryFirstSeen': {}}
    put_status, _ = _request(personal_server, 'PUT', '/api/personal', seed)
    assert put_status == 200
    empty = {'personal': {}, 'prefs': {}, 'manual': [], 'libraryFirstSeen': {}}
    status, err = _request(personal_server, 'PUT', '/api/personal', empty)
    assert status == 409
    assert err.get('error') == 'refusing empty overwrite'
    _, loaded = _request(personal_server, 'GET', '/api/personal')
    assert loaded['personal'] == seed['personal']

def test_personal_put_allows_empty_overwrite_with_opt_in_header(personal_server: str) -> None:
    seed = {'personal': {'steam:1': {'status': 'backlog'}}, 'prefs': {}, 'manual': [], 'libraryFirstSeen': {}}
    _request(personal_server, 'PUT', '/api/personal', seed)
    empty = {'personal': {}, 'prefs': {}, 'manual': [], 'libraryFirstSeen': {}}
    status, saved = _request(personal_server, 'PUT', '/api/personal', empty, extra_headers={server._BAKLOG_ALLOW_EMPTY_HEADER: '1'})
    assert status == 200
    assert saved['personal'] == {}

def test_personal_put_round_trip(personal_server: str):
    payload = {'personal': {'steam:570': {'status': 'backlog'}}, 'prefs': {'picksTab': 'topRated'}, 'manual': [{'store': 'manual', 'id': 'demo', 'name': 'Demo'}], 'libraryFirstSeen': {'steam:570': 1700000000000}}
    put_status, saved = _request(personal_server, 'PUT', '/api/personal', payload)
    assert put_status == 200
    assert saved['personal']['steam:570']['status'] == 'backlog'
    assert saved['manual'][0]['name'] == 'Demo'
    assert saved.get('updated_at') is not None
    get_status, loaded = _request(personal_server, 'GET', '/api/personal')
    assert get_status == 200
    assert loaded['personal'] == saved['personal']
    assert loaded['prefs'] == saved['prefs']
    assert loaded['manual'] == saved['manual']
    assert loaded['libraryFirstSeen'] == saved['libraryFirstSeen']

def test_personal_hidden_flag_round_trips(personal_server: str):
    payload = {'personal': {'steam:99': {'status': 'backlog', 'hidden': True}, 'gog:keep': {'status': 'playing', 'hidden': False}}, 'prefs': {}, 'manual': [{'store': 'gog', 'id': 'manual-1', 'name': 'Custom', 'manual': True}], 'libraryFirstSeen': {}}
    put_status, saved = _request(personal_server, 'PUT', '/api/personal', payload)
    assert put_status == 200
    assert saved['personal']['steam:99']['hidden'] is True
    assert saved['personal']['gog:keep']['hidden'] is False
    get_status, loaded = _request(personal_server, 'GET', '/api/personal')
    assert get_status == 200
    assert loaded['personal']['steam:99']['hidden'] is True
    assert loaded['manual'][0]['id'] == 'manual-1'

def test_personal_put_invalid_payload(personal_server: str):
    status, err = _request(personal_server, 'PUT', '/api/personal', {'personal': 'not-an-object'})
    assert status == 400
    assert 'personal must be an object' in err['error']

def test_personal_put_matching_profile_stamped(personal_server: str):
    payload = {'profile': 'default', 'personal': {'steam:1': {'status': 'backlog'}}, 'prefs': {}, 'manual': []}
    status, saved = _request(personal_server, 'PUT', '/api/personal', payload)
    assert status == 200
    assert saved['personal']['steam:1']['status'] == 'backlog'
    assert 'profile' not in saved

def test_personal_put_profile_mismatch_rejected(personal_server: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(profile_paths, 'ROOT', tmp_path)
    prof = tmp_path / 'profiles'
    prof.mkdir(parents=True)
    (prof / 'index.json').write_text(json.dumps({'active': 'default', 'profiles': [{'id': 'default', 'label': 'Default', 'created_at': 't'}]}), encoding='utf-8')
    server._refresh_personal_paths()
    seed = {'personal': {'keep': {'status': 'done'}}, 'prefs': {}, 'manual': []}
    _request(personal_server, 'PUT', '/api/personal', seed)
    status, err = _request(personal_server, 'PUT', '/api/personal', {'profile': 'work', 'personal': {'bad': {'status': 'x'}}, 'prefs': {}, 'manual': []})
    assert status == 409
    assert err.get('error') == 'profile mismatch'
    _, loaded = _request(personal_server, 'GET', '/api/personal')
    assert loaded['personal'] == seed['personal']

def test_personal_post_beacon_writes(personal_server: str):
    payload = {'profile': 'default', 'personal': {'steam:99': {'status': 'queued'}}, 'prefs': {}, 'manual': []}
    status, saved = _request(personal_server, 'POST', '/api/personal', payload)
    assert status == 200
    assert saved['personal']['steam:99']['status'] == 'queued'

def test_personal_put_without_profile_back_compat(personal_server: str):
    payload = {'personal': {'steam:2': {'status': 'live'}}, 'prefs': {}, 'manual': []}
    status, saved = _request(personal_server, 'PUT', '/api/personal', payload)
    assert status == 200
    assert saved['personal']['steam:2']['status'] == 'live'

def test_run_unknown_fetcher(personal_server: str):
    status, err = _request(personal_server, 'POST', '/api/run/unknown-fetcher-key')
    assert status == 404
    assert 'unknown fetcher' in err['error']

def test_fetchers_from_manifest(personal_server: str):
    status, data = _request(personal_server, 'GET', '/api/fetchers')
    assert status == 200
    keys = {entry['key'] for entry in data['fetchers']}
    assert 'steam' in keys
    assert 'hltb' in keys
    assert len(keys) == len(server.FETCHERS)

def test_missing_library_json_returns_empty_catalog(personal_server: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(profile_paths, 'ROOT', tmp_path)
    status, data = _request(personal_server, 'GET', '/games_ea.json')
    assert status == 200
    assert data == {'game_count': 0, 'games': []}

def test_profiles_create_and_switch(personal_server: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(profile_paths, 'ROOT', tmp_path)
    monkeypatch.setattr(profile_paths, 'PROFILES_DIR', tmp_path / 'profiles')
    monkeypatch.setattr(profile_paths, 'INDEX_FILE', tmp_path / 'profiles' / 'index.json')
    status, data = _request(personal_server, 'GET', '/api/profiles')
    assert status == 200
    assert data['active'] == 'default'
    assert data['legacy'] is True
    status, created = _request(personal_server, 'POST', '/api/profiles', {'label': 'Work'})
    assert status == 201
    assert created['id'] == 'work'
    assert (tmp_path / 'profiles' / 'default' / 'games_steam.json').exists() is False
    status, switched = _request(personal_server, 'POST', '/api/profiles/active', {'id': 'work'})
    assert status == 200
    assert switched['active'] == 'work'

def test_scoped_catalog_served_from_profile_dir(personal_server: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    work = tmp_path / 'profiles' / 'work'
    work.mkdir(parents=True)
    payload = {'game_count': 1, 'games': [{'id': '1', 'name': 'Scoped'}]}
    (work / 'games_steam.json').write_text(json.dumps(payload), encoding='utf-8')
    index = {'active': 'work', 'profiles': [{'id': 'default', 'label': 'Default', 'created_at': 't'}, {'id': 'work', 'label': 'Work', 'created_at': 't'}]}
    (tmp_path / 'profiles' / 'index.json').write_text(json.dumps(index), encoding='utf-8')
    monkeypatch.setattr(profile_paths, 'ROOT', tmp_path)
    monkeypatch.setattr(profile_paths, 'PROFILES_DIR', tmp_path / 'profiles')
    monkeypatch.setattr(profile_paths, 'INDEX_FILE', tmp_path / 'profiles' / 'index.json')
    status, data = _request(personal_server, 'GET', '/games_steam.json')
    assert status == 200
    assert data['game_count'] == 1
    assert data['games'][0]['name'] == 'Scoped'