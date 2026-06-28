"""Tests for POST /api/catalogs/import."""

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
from shared.server_catalog_import import is_allowed_catalog_filename, validate_catalog_doc


@pytest.fixture()
def catalog_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    prof = tmp_path / "profiles"
    monkeypatch.setattr(profile_paths, "ROOT", tmp_path)
    monkeypatch.setattr(profile_paths, "PROFILES_DIR", prof)
    monkeypatch.setattr(profile_paths, "INDEX_FILE", prof / "index.json")
    server._refresh_personal_paths()

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(server.Handler, directory=str(server.ROOT)))
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _post(base: str, path: str, body: dict) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{base}{path}",
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-BAKLOG-Local": "1",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"error": raw}


def test_catalog_filename_whitelist() -> None:
    assert is_allowed_catalog_filename("games_steam.json")
    assert is_allowed_catalog_filename("games_wishlist_gog.json")
    assert is_allowed_catalog_filename("itad_prices.json")
    assert not is_allowed_catalog_filename("personal.json")
    assert not is_allowed_catalog_filename("../games_steam.json")


def test_validate_catalog_doc_games_list() -> None:
    validate_catalog_doc("games_steam.json", {"games": []})
    with pytest.raises(ValueError, match="games must be a list"):
        validate_catalog_doc("games_steam.json", {"games": {}})


def test_catalog_import_round_trip(catalog_server: str, tmp_path: Path) -> None:
    payload = {
        "catalogs": {
            "games_steam.json": {
                "games": [{"store": "steam", "id": "570", "name": "Dota 2"}],
                "fetched_at": "2026-06-25T00:00:00Z",
            },
            "itad_prices.json": {"currency": "USD", "prices": {}},
        },
    }
    status, body = _post(catalog_server, "/api/catalogs/import", payload)
    assert status == 200
    assert body["count"] == 2
    assert "games_steam.json" in body["imported"]

    disk = profile_paths.catalog_path("games_steam.json")
    saved = json.loads(disk.read_text(encoding="utf-8"))
    assert saved["games"][0]["name"] == "Dota 2"


def test_catalog_import_rejects_bad_filename(catalog_server: str) -> None:
    status, body = _post(
        catalog_server,
        "/api/catalogs/import",
        {"catalogs": {"secrets.bin": {"games": []}}},
    )
    assert status == 400
    assert "disallowed" in body.get("error", "")
