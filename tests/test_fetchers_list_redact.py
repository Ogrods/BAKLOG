"""GET /api/fetchers must not leak exception text to the client."""

from __future__ import annotations

import json
import threading
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
import urllib.error
import urllib.request

import server
from shared import profile_paths


@pytest.fixture()
def fetchers_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    prof = tmp_path / "profiles"
    monkeypatch.setattr(profile_paths, "ROOT", tmp_path)
    monkeypatch.setattr(profile_paths, "PROFILES_DIR", prof)
    monkeypatch.setattr(profile_paths, "INDEX_FILE", prof / "index.json")
    monkeypatch.delenv("BAKLOG_SUPABASE_URL", raising=False)
    monkeypatch.delenv("BAKLOG_SUPABASE_ANON_KEY", raising=False)
    server._refresh_personal_paths()

    httpd = ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(server.Handler, directory=str(server.ROOT))
    )
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_fetchers_list_redacts_exception(
    fetchers_server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        server,
        "_fetcher_cmd_label",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("secret-path-leak")),
    )
    req = urllib.request.Request(f"{fetchers_server}/api/fetchers", method="GET")
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req, timeout=5)
    assert exc_info.value.code == 500
    body = json.loads(exc_info.value.read().decode("utf-8"))
    assert body.get("error") == "fetchers_list_failed"
    assert "secret-path-leak" not in json.dumps(body)
