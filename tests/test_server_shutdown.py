from __future__ import annotations
import json
import threading
import time
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
import pytest
import server

@pytest.fixture()
def shutdown_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    runs_dir = tmp_path / 'runs'
    monkeypatch.setattr(server, 'RUNS_DIR', runs_dir)
    monkeypatch.setattr(server, 'ACTIVE_RUNS_FILE', runs_dir / 'active.json')
    monkeypatch.setattr(server, 'RUN_HISTORY_FILE', runs_dir / 'history.json')
    monkeypatch.setattr(server, 'QUEUE_FILE', runs_dir / 'queue.json')
    monkeypatch.setattr(server, 'SCHEDULER', None)
    monkeypatch.setattr(server, 'MANAGER', server.RunManager(runs_dir=runs_dir))
    httpd = ThreadingHTTPServer(('127.0.0.1', 0), partial(server.Handler, directory=str(server.ROOT)))
    port = httpd.server_address[1]
    monkeypatch.setattr(server, '_DEV_HTTPD', httpd, raising=False)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{port}'
    finally:
        server.MANAGER.shutdown()
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
        monkeypatch.setattr(server, '_DEV_HTTPD', None, raising=False)

def _post(base: str, path: str, *, local_header: bool=False) -> tuple[int, dict]:
    import urllib.error
    import urllib.request
    headers: dict[str, str] = {}
    if local_header:
        headers[server._BAKLOG_LOCAL_HEADER] = '1'
    req = urllib.request.Request(f'{base}{path}', method='POST', headers=headers, data=b'')
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

def test_shutdown_requires_local_header(shutdown_server: str) -> None:
    status, body = _post(shutdown_server, '/api/shutdown')
    assert status == 403
    assert 'cross-origin' in body.get('error', '').lower()

def test_shutdown_ok_with_local_header(shutdown_server: str) -> None:
    status, body = _post(shutdown_server, '/api/shutdown', local_header=True)
    assert status == 200
    assert body.get('ok') is True
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        time.sleep(0.05)