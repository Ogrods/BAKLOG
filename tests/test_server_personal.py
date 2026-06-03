"""Tests for server.py personal-data API."""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from functools import partial
from pathlib import Path

import pytest

import server
from shared import profile_paths


@pytest.fixture()
def personal_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Run server.Handler on an ephemeral port with isolated personal-data files."""
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


def _request(base: str, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{base}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8")
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            parsed = {"error": payload}
        return exc.code, parsed


def test_personal_get_empty_doc(personal_server: str):
    status, doc = _request(personal_server, "GET", "/api/personal")
    assert status == 200
    assert doc["personal"] == {}
    assert doc["prefs"] == {}
    assert doc["manual"] == []
    assert doc["libraryFirstSeen"] == {}
    assert doc["schema_version"] == 1


def test_personal_put_round_trip(personal_server: str):
    payload = {
        "personal": {"steam:570": {"status": "backlog"}},
        "prefs": {"picksTab": "topRated"},
        "manual": [{"store": "manual", "id": "demo", "name": "Demo"}],
        "libraryFirstSeen": {"steam:570": 1_700_000_000_000},
    }
    put_status, saved = _request(personal_server, "PUT", "/api/personal", payload)
    assert put_status == 200
    assert saved["personal"]["steam:570"]["status"] == "backlog"
    assert saved["manual"][0]["name"] == "Demo"
    assert saved.get("updated_at") is not None

    get_status, loaded = _request(personal_server, "GET", "/api/personal")
    assert get_status == 200
    assert loaded["personal"] == saved["personal"]
    assert loaded["prefs"] == saved["prefs"]
    assert loaded["manual"] == saved["manual"]
    assert loaded["libraryFirstSeen"] == saved["libraryFirstSeen"]


def test_personal_put_invalid_payload(personal_server: str):
    status, err = _request(personal_server, "PUT", "/api/personal", {"personal": "not-an-object"})
    assert status == 400
    assert "personal must be an object" in err["error"]


def test_run_unknown_fetcher(personal_server: str):
    status, err = _request(personal_server, "POST", "/api/run/unknown-fetcher-key")
    assert status == 404
    assert "unknown fetcher" in err["error"]


def test_fetchers_from_manifest(personal_server: str):
    status, data = _request(personal_server, "GET", "/api/fetchers")
    assert status == 200
    keys = {entry["key"] for entry in data["fetchers"]}
    assert "steam" in keys
    assert "hltb" in keys
    assert len(keys) == len(server.FETCHERS)


def test_missing_library_json_returns_empty_catalog(personal_server: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(profile_paths, "ROOT", tmp_path)
    status, data = _request(personal_server, "GET", "/games_ea.json")
    assert status == 200
    assert data == {"game_count": 0, "games": []}


def test_profiles_create_and_switch(personal_server: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(profile_paths, "ROOT", tmp_path)
    monkeypatch.setattr(profile_paths, "PROFILES_DIR", tmp_path / "profiles")
    monkeypatch.setattr(profile_paths, "INDEX_FILE", tmp_path / "profiles" / "index.json")
    status, data = _request(personal_server, "GET", "/api/profiles")
    assert status == 200
    assert data["active"] == "default"
    assert data["legacy"] is True

    status, created = _request(personal_server, "POST", "/api/profiles", {"label": "Work"})
    assert status == 201
    assert created["id"] == "work"
    assert (tmp_path / "profiles" / "default" / "games_steam.json").exists() is False  # no root games to copy

    status, switched = _request(personal_server, "POST", "/api/profiles/active", {"id": "work"})
    assert status == 200
    assert switched["active"] == "work"


def test_scoped_catalog_served_from_profile_dir(
    personal_server: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    work = tmp_path / "profiles" / "work"
    work.mkdir(parents=True)
    payload = {"game_count": 1, "games": [{"id": "1", "name": "Scoped"}]}
    (work / "games_steam.json").write_text(json.dumps(payload), encoding="utf-8")
    index = {
        "active": "work",
        "profiles": [
            {"id": "default", "label": "Default", "created_at": "t"},
            {"id": "work", "label": "Work", "created_at": "t"},
        ],
    }
    (tmp_path / "profiles" / "index.json").write_text(json.dumps(index), encoding="utf-8")
    monkeypatch.setattr(profile_paths, "ROOT", tmp_path)
    monkeypatch.setattr(profile_paths, "PROFILES_DIR", tmp_path / "profiles")
    monkeypatch.setattr(profile_paths, "INDEX_FILE", tmp_path / "profiles" / "index.json")

    status, data = _request(personal_server, "GET", "/games_steam.json")
    assert status == 200
    assert data["game_count"] == 1
    assert data["games"][0]["name"] == "Scoped"
