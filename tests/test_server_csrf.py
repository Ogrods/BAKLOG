"""CSRF / localhost guard on mutating API routes."""

from __future__ import annotations

import json
import threading
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

import server
from shared import profile_paths


@pytest.fixture()
def csrf_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    runs_dir = tmp_path / "runs"
    # Isolate the personal-data path: without this the PUT /api/personal test
    # writes to the developer's real profiles/default/data/personal.json. On a
    # populated dev machine the empty-overwrite guard then returns 409 instead of
    # 200 (CI passes only because a fresh checkout has no personal.json).
    prof = tmp_path / "profiles"
    monkeypatch.setattr(profile_paths, "ROOT", tmp_path)
    monkeypatch.setattr(profile_paths, "PROFILES_DIR", prof)
    monkeypatch.setattr(profile_paths, "INDEX_FILE", prof / "index.json")
    server._refresh_personal_paths()
    monkeypatch.setattr(server, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(server, "ACTIVE_RUNS_FILE", runs_dir / "active.json")
    monkeypatch.setattr(server, "RUN_HISTORY_FILE", runs_dir / "history.json")
    monkeypatch.setattr(server, "QUEUE_FILE", runs_dir / "queue.json")
    monkeypatch.setitem(
        server.FETCHERS,
        "demo",
        {
            "label": "Demo",
            "argv": [server.sys.executable, "-c", "print('ok')"],
            "refreshArgs": [],
            "metaKey": "demo",
            "group": "library",
            "color": "#fff",
            "requires": [],
        },
    )
    monkeypatch.setattr(server, "MANAGER", server.RunManager(runs_dir=runs_dir))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(server.Handler, directory=str(server.ROOT)))
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.MANAGER.shutdown()
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _post(
    base: str,
    path: str,
    *,
    origin: str | None = None,
    local_header: bool = False,
) -> tuple[int, dict]:
    import urllib.error
    import urllib.request

    headers: dict[str, str] = {}
    if origin is not None:
        headers["Origin"] = origin
    if local_header:
        headers[server._BAKLOG_LOCAL_HEADER] = "1"
    req = urllib.request.Request(
        f"{base}{path}",
        method="POST",
        headers=headers,
        data=b"",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8")
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            parsed = {"error": payload}
        return exc.code, parsed


def test_cross_origin_post_blocked(csrf_server: str) -> None:
    status, body = _post(csrf_server, "/api/runs/cancel", origin="https://evil.example")
    assert status == 403
    assert "cross-origin" in body.get("error", "").lower()


def test_local_header_post_allowed(csrf_server: str) -> None:
    status, _body = _post(csrf_server, "/api/runs/cancel", local_header=True)
    assert status == 200


def test_local_origin_post_allowed(csrf_server: str) -> None:
    base = csrf_server
    status, _body = _post(base, "/api/runs/cancel", origin=base)
    assert status == 200


def _put_personal(
    base: str,
    *,
    origin: str | None = None,
    local_header: bool = False,
) -> tuple[int, dict]:
    import urllib.error
    import urllib.request

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if origin is not None:
        headers["Origin"] = origin
    if local_header:
        headers[server._BAKLOG_LOCAL_HEADER] = "1"
    body = json.dumps({"personal": {}, "prefs": {}, "manual": []}).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/api/personal",
        method="PUT",
        headers=headers,
        data=body,
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8")
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            parsed = {"error": payload}
        return exc.code, parsed


def test_personal_put_requires_local_header_not_origin_only(csrf_server: str) -> None:
    base = csrf_server
    status, body = _put_personal(base, origin=base)
    assert status == 403
    assert "cross-origin" in body.get("error", "").lower()


def test_personal_put_allowed_with_local_header(csrf_server: str) -> None:
    status, _body = _put_personal(csrf_server, local_header=True)
    assert status == 200
