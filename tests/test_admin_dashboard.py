"""Tests for env-gated internal admin dashboard API."""

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


def _request(
    base: str,
    method: str,
    path: str,
    *,
    body: dict | None = None,
) -> tuple[int, dict | str]:
    headers = {}
    data = None
    if method != "GET":
        headers[server._BAKLOG_LOCAL_HEADER] = "1"
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        f"{base}{path}",
        method=method,
        headers=headers,
        data=data,
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw


@pytest.fixture()
def admin_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    runs_dir = tmp_path / "runs"
    claims_input = tmp_path / "free-claims.input.json"
    claims_input.write_text(json.dumps({"items": []}), encoding="utf-8")
    monkeypatch.setattr(server, "ADMIN_ENABLED", True)
    monkeypatch.setattr(server, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(server, "ACTIVE_RUNS_FILE", runs_dir / "active.json")
    monkeypatch.setattr(server, "RUN_HISTORY_FILE", runs_dir / "history.json")
    monkeypatch.setattr(server, "QUEUE_FILE", runs_dir / "queue.json")
    monkeypatch.setattr(server, "FREE_CLAIMS_INPUT_PATH", Path("free-claims.input.json"))
    monkeypatch.setattr(server, "MANAGER", server.RunManager(runs_dir=runs_dir))
    monkeypatch.setattr(server, "data_root", lambda: tmp_path)
    httpd = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        partial(server.Handler, directory=str(server.ROOT)),
    )
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}", claims_input
    finally:
        server.MANAGER.shutdown()
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


@pytest.fixture()
def admin_off_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(server, "ADMIN_ENABLED", False)
    httpd = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        partial(server.Handler, directory=str(server.ROOT)),
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


def test_admin_disabled_returns_404(admin_off_server: str) -> None:
    base = admin_off_server
    code, _ = _request(base, "GET", "/api/internal/jobs")
    assert code == 404
    try:
        req = urllib.request.Request(f"{base}/admin/index.html", method="GET")
        urllib.request.urlopen(req, timeout=5)
        assert False, "expected 404"
    except urllib.error.HTTPError as exc:
        assert exc.code == 404


def test_admin_lists_builtin_jobs(admin_server: tuple[str, Path]) -> None:
    base, _ = admin_server
    code, data = _request(base, "GET", "/api/internal/jobs")
    assert code == 200
    keys = {j["key"] for j in data["jobs"]}
    assert keys == {"claimSources", "buildClaims"}


def test_internal_run_rejects_unknown_option(admin_server: tuple[str, Path]) -> None:
    base, _ = admin_server
    code, data = _request(
        base,
        "POST",
        "/api/internal/run/claimSources",
        body={"args": {"--bogus": True}},
    )
    assert code == 400
    assert "unknown option" in str(data.get("error", ""))


def test_internal_run_rejects_bad_enum(admin_server: tuple[str, Path]) -> None:
    base, _ = admin_server
    code, data = _request(
        base,
        "POST",
        "/api/internal/run/claimSources",
        body={"args": {"--source": "nope"}},
    )
    assert code == 400
    assert "invalid value" in str(data.get("error", ""))


def test_internal_run_unknown_key(admin_server: tuple[str, Path]) -> None:
    base, _ = admin_server
    code, data = _request(base, "POST", "/api/internal/run/notAJob", body={"args": {}})
    assert code == 404
    assert "unknown internal job" in str(data.get("error", ""))


def test_internal_job_skips_fetcher_key_collision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(server.FETCHERS, "customJob", server.FETCHERS["claims"])
    overlay = server.INTERNAL_JOBS_OVERLAY
    overlay.parent.mkdir(parents=True, exist_ok=True)
    overlay.write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "key": "customJob",
                        "label": "Should skip",
                        "script": "fetch_free_claims.py",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    try:
        jobs = server._load_internal_jobs()
        assert "customJob" not in jobs
    finally:
        if overlay.is_file():
            overlay.unlink()


def test_free_claims_put_validation(admin_server: tuple[str, Path]) -> None:
    base, _ = admin_server
    code, data = _request(
        base,
        "PUT",
        "/api/internal/free-claims",
        body={"items": [{"id": "x", "store": "steam"}]},
    )
    assert code == 400
    assert "missing" in str(data.get("error", ""))


def test_free_claims_put_writes_file(admin_server: tuple[str, Path]) -> None:
    base, claims_input = admin_server
    payload = {
        "items": [
            {
                "id": "steam-test",
                "store": "steam",
                "title": "Test Game",
                "claim_url": "https://store.steampowered.com/app/570",
            }
        ]
    }
    code, data = _request(base, "PUT", "/api/internal/free-claims", body=payload)
    assert code == 200
    assert data.get("items") == 1
    saved = json.loads(claims_input.read_text(encoding="utf-8"))
    assert saved["items"][0]["title"] == "Test Game"


def test_free_claims_get_returns_approved(admin_server: tuple[str, Path], tmp_path: Path) -> None:
    base, _ = admin_server
    approved_path = tmp_path / "curated" / "free_claims.approved.json"
    approved_path.parent.mkdir(parents=True, exist_ok=True)
    approved_path.write_text(json.dumps({"ids": ["epic-a", "gamerpower-1"]}), encoding="utf-8")
    code, data = _request(base, "GET", "/api/internal/free-claims")
    assert code == 200
    assert data.get("approved") == ["epic-a", "gamerpower-1"]


def test_free_claims_approved_put_validation(admin_server: tuple[str, Path]) -> None:
    base, _ = admin_server
    code, data = _request(
        base,
        "PUT",
        "/api/internal/free-claims/approved",
        body={"ids": ["ok", ""]},
    )
    assert code == 400
    assert "ids[1]" in str(data.get("error", ""))


def test_free_claims_approved_put_writes_file(admin_server: tuple[str, Path], tmp_path: Path) -> None:
    base, _ = admin_server
    approved_path = tmp_path / "curated" / "free_claims.approved.json"
    payload = {"ids": ["epic-approved", "gamerpower-42"]}
    code, data = _request(base, "PUT", "/api/internal/free-claims/approved", body=payload)
    assert code == 200
    assert data.get("ids") == 2
    saved = json.loads(approved_path.read_text(encoding="utf-8"))
    assert saved["ids"] == ["epic-approved", "gamerpower-42"]


def test_sponsors_put_validation(admin_server: tuple[str, Path]) -> None:
    base, _ = admin_server
    code, data = _request(
        base,
        "PUT",
        "/api/internal/sponsors",
        body={"items": [{"id": "sp1", "title": "Ad", "url": "ftp://bad.example"}]},
    )
    assert code == 400
    assert "url must start with http" in str(data.get("error", ""))


def test_sponsors_put_writes_file(admin_server: tuple[str, Path], tmp_path: Path) -> None:
    base, _ = admin_server
    sponsors_path = tmp_path / "curated" / "sponsors.json"
    sponsors_path.parent.mkdir(parents=True, exist_ok=True)
    sponsors_path.write_text(json.dumps({"items": []}), encoding="utf-8")
    payload = {
        "items": [
            {
                "id": "house-test",
                "kind": "house",
                "title": "Back BAKLOG",
                "tagline": "Support local-first backlog",
                "cta": "Learn more",
                "url": "https://baklog.app/#waitlist",
                "enabled": True,
                "priority": 0,
            }
        ]
    }
    code, data = _request(base, "PUT", "/api/internal/sponsors", body=payload)
    assert code == 200
    assert data.get("items") == 1
    saved = json.loads(sponsors_path.read_text(encoding="utf-8"))
    assert saved["items"][0]["title"] == "Back BAKLOG"


def test_sponsors_get_returns_input(admin_server: tuple[str, Path], tmp_path: Path) -> None:
    base, _ = admin_server
    sponsors_path = tmp_path / "curated" / "sponsors.json"
    sponsors_path.parent.mkdir(parents=True, exist_ok=True)
    sponsors_path.write_text(
        json.dumps({"items": [{"id": "a", "title": "Existing"}]}),
        encoding="utf-8",
    )
    code, data = _request(base, "GET", "/api/internal/sponsors")
    assert code == 200
    assert data["input"]["items"][0]["id"] == "a"


def test_validate_internal_args_bool_and_enum() -> None:
    spec = server.INTERNAL_JOBS["claimSources"]
    argv = server.validate_internal_args(spec, {"--dry-run": True, "--source": "epic"})
    assert argv == ["--dry-run", "--source", "epic"]
    argv_default = server.validate_internal_args(spec, {"--source": "all"})
    assert argv_default == []
