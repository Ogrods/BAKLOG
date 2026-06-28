from __future__ import annotations
import json
import threading
import time
import urllib.error
import urllib.request
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
import pytest
import server

@pytest.fixture()
def run_api_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    runs_dir = tmp_path / 'runs'
    monkeypatch.setattr(server, 'RUNS_DIR', runs_dir)
    monkeypatch.setattr(server, 'ACTIVE_RUNS_FILE', runs_dir / 'active.json')
    monkeypatch.setattr(server, 'RUN_HISTORY_FILE', runs_dir / 'history.json')
    monkeypatch.setattr(server, 'QUEUE_FILE', runs_dir / 'queue.json')
    monkeypatch.setitem(server.FETCHERS, 'demo', {'label': 'Demo', 'argv': [server.sys.executable, '-c', "print('ok')"], 'refreshArgs': [], 'metaKey': 'demo', 'group': 'library', 'color': '#fff', 'requires': []})
    monkeypatch.setitem(server.FETCHERS, 'demo', {'label': 'Demo', 'argv': [server.sys.executable, '-c', 'import time; time.sleep(2)'], 'refreshArgs': [], 'metaKey': 'demo', 'group': 'library', 'color': '#fff', 'requires': []})
    monkeypatch.setattr(server, 'MANAGER', server.RunManager(runs_dir=runs_dir))
    httpd = ThreadingHTTPServer(('127.0.0.1', 0), partial(server.Handler, directory=str(server.ROOT)))
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{port}'
    finally:
        server.MANAGER.shutdown()
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)

def _request(base: str, method: str, path: str) -> tuple[int, dict]:
    headers = {}
    if method != 'GET':
        headers[server._BAKLOG_LOCAL_HEADER] = '1'
    req = urllib.request.Request(f'{base}{path}', method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return (resp.status, json.loads(resp.read().decode('utf-8')))
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode('utf-8')
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            parsed = {'error': payload}
        return (exc.code, parsed)

def test_runs_cancel_all(run_api_server: str):
    base = run_api_server
    _request(base, 'POST', '/api/run/demo')
    status, data = _request(base, 'POST', '/api/runs/cancel')
    assert status == 200
    assert isinstance(data.get('cancelled'), list)
    deadline = time.time() + 5
    while time.time() < deadline:
        _, snap = _request(base, 'GET', '/api/runs')
        if snap['active'] is None and snap['queue'] == []:
            break
        time.sleep(0.05)
    else:
        pytest.fail('runs not cleared after cancel')

def test_runs_snapshot_shape(run_api_server: str):
    base = run_api_server
    status, snap = _request(base, 'GET', '/api/runs')
    assert status == 200
    assert 'active' in snap and 'queue' in snap and ('history' in snap)