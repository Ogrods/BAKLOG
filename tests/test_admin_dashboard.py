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


def test_free_claims_put_rejects_bad_claim_url(admin_server: tuple[str, Path]) -> None:
    base, _ = admin_server
    code, data = _request(
        base,
        "PUT",
        "/api/internal/free-claims",
        body={
            "items": [
                {
                    "id": "bad-url",
                    "store": "steam",
                    "title": "Bad",
                    "claim_url": "javascript:alert(1)",
                }
            ]
        },
    )
    assert code == 400
    assert "claim_url" in str(data.get("error", ""))


def test_internal_enrich_requires_local_header(admin_server: tuple[str, Path]) -> None:
    base, _ = admin_server
    payload = json.dumps({"items": []}).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/api/internal/free-claims/enrich",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=payload,
    )
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req, timeout=10)
    assert exc.value.code == 403


def test_internal_enrich_rejects_oversized_batch(
    admin_server: tuple[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base, _ = admin_server
    monkeypatch.setattr(server, "MAX_ADMIN_ENRICH_BATCH", 2)
    code, data = _request(
        base,
        "POST",
        "/api/internal/free-claims/enrich",
        body={"items": [{}, {}, {}]},
    )
    assert code == 400
    assert "maximum" in str(data.get("error", ""))


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
    assert data.get("field_overrides") == {}


def test_free_claims_get_returns_field_overrides(admin_server: tuple[str, Path], tmp_path: Path) -> None:
    base, _ = admin_server
    approved_path = tmp_path / "curated" / "free_claims.approved.json"
    approved_path.parent.mkdir(parents=True, exist_ok=True)
    approved_path.write_text(
        json.dumps(
            {
                "ids": ["epic-a"],
                "field_overrides": {
                    "epic-a": {
                        "title": "Custom Title",
                        "claim_url": "https://store.epicgames.com/en-US/p/custom",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    code, data = _request(base, "GET", "/api/internal/free-claims")
    assert code == 200
    assert data.get("field_overrides") == {
        "epic-a": {
            "title": "Custom Title",
            "claim_url": "https://store.epicgames.com/en-US/p/custom",
        }
    }


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


def test_free_claims_approved_put_writes_field_overrides(
    admin_server: tuple[str, Path],
    tmp_path: Path,
) -> None:
    base, _ = admin_server
    approved_path = tmp_path / "curated" / "free_claims.approved.json"
    payload = {
        "ids": ["epic-approved"],
        "field_overrides": {
            "epic-approved": {
                "title": "Edited",
                "claim_url": "https://store.epicgames.com/en-US/p/edited",
                "ends_at": "2099-01-01T00:00:00Z",
            },
            "ignored-id": {"title": "Should Drop"},
        },
    }
    code, data = _request(base, "PUT", "/api/internal/free-claims/approved", body=payload)
    assert code == 200
    saved = json.loads(approved_path.read_text(encoding="utf-8"))
    assert saved["field_overrides"] == {
        "epic-approved": {
            "title": "Edited",
            "claim_url": "https://store.epicgames.com/en-US/p/edited",
            "ends_at": "2099-01-01T00:00:00Z",
        },
        "ignored-id": {"title": "Should Drop"},
    }


def test_free_claims_get_returns_dismissed(admin_server: tuple[str, Path], tmp_path: Path) -> None:
    base, _ = admin_server
    approved_path = tmp_path / "curated" / "free_claims.approved.json"
    approved_path.parent.mkdir(parents=True, exist_ok=True)
    approved_path.write_text(
        json.dumps({"ids": ["epic-a"], "dismissed": ["gamerpower-junk"]}),
        encoding="utf-8",
    )
    code, data = _request(base, "GET", "/api/internal/free-claims")
    assert code == 200
    assert data.get("dismissed") == ["gamerpower-junk"]


def test_free_claims_approved_put_writes_dismissed(
    admin_server: tuple[str, Path],
    tmp_path: Path,
) -> None:
    base, _ = admin_server
    approved_path = tmp_path / "curated" / "free_claims.approved.json"
    payload = {
        "ids": ["epic-approved"],
        "dismissed": ["gamerpower-junk", "gamerpower-junk", "epic-approved"],
    }
    code, data = _request(base, "PUT", "/api/internal/free-claims/approved", body=payload)
    assert code == 200
    saved = json.loads(approved_path.read_text(encoding="utf-8"))
    # Deduped, and ids that are also approved are excluded.
    assert saved["dismissed"] == ["gamerpower-junk"]


def test_free_claims_approved_put_dismissed_validation(
    admin_server: tuple[str, Path],
) -> None:
    base, _ = admin_server
    code, data = _request(
        base,
        "PUT",
        "/api/internal/free-claims/approved",
        body={"ids": ["epic-a"], "dismissed": ["ok", ""]},
    )
    assert code == 400
    assert "dismissed[1]" in str(data.get("error", ""))


def test_free_claims_get_returns_premium_only_ids(
    admin_server: tuple[str, Path],
    tmp_path: Path,
) -> None:
    base, _ = admin_server
    approved_path = tmp_path / "curated" / "free_claims.approved.json"
    approved_path.parent.mkdir(parents=True, exist_ok=True)
    approved_path.write_text(
        json.dumps({"ids": ["epic-a"], "premium_only_ids": ["epic-a"]}),
        encoding="utf-8",
    )
    code, data = _request(base, "GET", "/api/internal/free-claims")
    assert code == 200
    assert data.get("premium_only_ids") == ["epic-a"]


def test_free_claims_approved_put_writes_premium_only_ids(
    admin_server: tuple[str, Path],
    tmp_path: Path,
) -> None:
    base, _ = admin_server
    approved_path = tmp_path / "curated" / "free_claims.approved.json"
    payload = {
        "ids": ["epic-approved", "gamerpower-42"],
        "premium_only_ids": ["epic-approved", "gamerpower-42", "not-approved"],
    }
    code, data = _request(base, "PUT", "/api/internal/free-claims/approved", body=payload)
    assert code == 200
    saved = json.loads(approved_path.read_text(encoding="utf-8"))
    assert saved["premium_only_ids"] == ["epic-approved", "gamerpower-42"]


def test_free_claims_approved_put_premium_only_validation(
    admin_server: tuple[str, Path],
) -> None:
    base, _ = admin_server
    code, data = _request(
        base,
        "PUT",
        "/api/internal/free-claims/approved",
        body={"ids": ["epic-a"], "premium_only_ids": ["ok", ""]},
    )
    assert code == 400
    assert "premium_only_ids[1]" in str(data.get("error", ""))


def test_free_claims_preview_stamps_premium_only(
    admin_server: tuple[str, Path],
) -> None:
    base, _ = admin_server
    payload = {
        "manual_items": [],
        "auto_items": [{
            "id": "auto-pro",
            "store": "steam",
            "title": "Bonus DLC",
            "claim_url": "https://example.com/bonus",
        }],
        "approved_ids": ["auto-pro"],
        "premium_only_ids": ["auto-pro"],
    }
    code, data = _request(base, "POST", "/api/internal/free-claims/preview", body=payload)
    assert code == 200
    items = data.get("items") or []
    assert len(items) == 1
    assert items[0].get("premium_only") is True


def test_free_claims_approved_put_field_overrides_validation(
    admin_server: tuple[str, Path],
) -> None:
    base, _ = admin_server
    code, data = _request(
        base,
        "PUT",
        "/api/internal/free-claims/approved",
        body={
            "ids": ["epic-a"],
            "field_overrides": {"epic-a": {"bad_key": "nope"}},
        },
    )
    assert code == 400
    assert "unknown key" in str(data.get("error", ""))


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


def test_sponsors_put_rejects_bad_cover(admin_server: tuple[str, Path]) -> None:
    base, _ = admin_server
    code, data = _request(
        base,
        "PUT",
        "/api/internal/sponsors",
        body={"items": [{"id": "sp1", "title": "Ad", "cover": "//evil.example/x.png"}]},
    )
    assert code == 400
    assert "cover must be" in str(data.get("error", ""))


def test_sponsors_put_accepts_cover_and_placements(
    admin_server: tuple[str, Path], tmp_path: Path
) -> None:
    base, _ = admin_server
    sponsors_path = tmp_path / "curated" / "sponsors.json"
    sponsors_path.parent.mkdir(parents=True, exist_ok=True)
    sponsors_path.write_text(json.dumps({"items": []}), encoding="utf-8")
    payload = {
        "items": [
            {
                "id": "ad-hero",
                "kind": "sponsor",
                "title": "Emberfall",
                "url": "https://example.com/deal",
                "cover": "/assets/ads-sample/hero-emberfall.webp",
                "placements": "spotlight, picks",
                "enabled": True,
            }
        ]
    }
    code, data = _request(base, "PUT", "/api/internal/sponsors", body=payload)
    assert code == 200
    saved = json.loads(sponsors_path.read_text(encoding="utf-8"))
    assert saved["items"][0]["cover"] == "/assets/ads-sample/hero-emberfall.webp"
    assert saved["items"][0]["placements"] == "spotlight, picks"


def test_sponsors_put_accepts_dash_deal_rail_placement(
    admin_server: tuple[str, Path], tmp_path: Path
) -> None:
    base, _ = admin_server
    sponsors_path = tmp_path / "curated" / "sponsors.json"
    sponsors_path.parent.mkdir(parents=True, exist_ok=True)
    sponsors_path.write_text(json.dumps({"items": []}), encoding="utf-8")
    payload = {
        "items": [
            {
                "id": "house-pro-promo",
                "kind": "house",
                "title": "Power-user conveniences",
                "url": "https://baklog.app/",
                "placements": "dash-deal-rail",
                "enabled": True,
            }
        ]
    }
    code, data = _request(base, "PUT", "/api/internal/sponsors", body=payload)
    assert code == 200
    saved = json.loads(sponsors_path.read_text(encoding="utf-8"))
    assert saved["items"][0]["placements"] == "dash-deal-rail"


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


def test_free_claims_enrich_returns_items_without_writing_feed(
    admin_server: tuple[str, Path],
    tmp_path: Path,
) -> None:
    base, _ = admin_server
    built_path = tmp_path / "landing" / "free-claims.json"
    fallback_path = tmp_path / "curated" / "free_claims.fallback.json"
    payload = {
        "items": [
            {
                "id": "itch-demo",
                "store": "itch",
                "title": "Demo on itch.io",
                "claim_url": "https://example.itch.io/demo",
                "blurb": "A free itch.io giveaway",
            }
        ]
    }
    code, data = _request(base, "POST", "/api/internal/free-claims/enrich", body=payload)
    assert code == 200
    items = data.get("items")
    assert isinstance(items, list)
    assert len(items) == 1
    enriched = items[0]
    assert enriched["id"] == "itch-demo"
    assert enriched["store"] == "itch"
    assert enriched["title"] == "Demo on itch.io"
    assert enriched["claim_url"] == "https://example.itch.io/demo"
    assert enriched.get("blurb") == "A free itch.io giveaway"
    assert not built_path.is_file()
    assert not fallback_path.is_file()


def test_free_claims_enrich_persists_auto_feed(
    admin_server: tuple[str, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base, _ = admin_server
    auto_path = tmp_path / "curated" / "free_claims.auto.json"
    auto_path.parent.mkdir(parents=True, exist_ok=True)
    auto_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "itad-b07aac9ebd26",
                        "store": "epic",
                        "title": "Wytchwood",
                        "claim_url": "https://example.com/w",
                        "header_image": None,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    import build_free_claims as bfc

    def fake_enrich(raw: dict, last_call: list[float], cover_lookup=None) -> dict:
        return {
            **raw,
            "header_image": bfc._steam_portrait_cover(729000),
            "steam_appid": 729000,
            "review_percent": 93,
        }

    monkeypatch.setattr(bfc, "_enrich_item", fake_enrich)

    code, data = _request(
        base,
        "POST",
        "/api/internal/free-claims/enrich",
        body={
            "items": [
                {
                    "id": "itad-b07aac9ebd26",
                    "store": "epic",
                    "title": "Wytchwood",
                    "claim_url": "https://example.com/w",
                }
            ]
        },
    )
    assert code == 200
    assert data.get("persisted") == 1
    saved = json.loads(auto_path.read_text(encoding="utf-8"))
    row = saved["items"][0]
    assert row["header_image"] == bfc._steam_portrait_cover(729000)
    assert row["steam_appid"] == 729000
    assert row["review_percent"] == 93


def test_free_claims_enrich_rejects_bad_payload(admin_server: tuple[str, Path]) -> None:
    base, _ = admin_server
    code, data = _request(
        base,
        "POST",
        "/api/internal/free-claims/enrich",
        body={"items": "not-a-list"},
    )
    assert code == 400
    assert "items must be a list" in str(data.get("error", ""))


def test_free_claims_preview_dry_run_merge(
    admin_server: tuple[str, Path],
    tmp_path: Path,
) -> None:
    base, _ = admin_server
    built_path = tmp_path / "landing" / "free-claims.json"
    payload = {
        "manual_items": [
            {
                "id": "manual-1",
                "store": "steam",
                "title": "Manual Game",
                "claim_url": "https://store.steampowered.com/app/1",
            }
        ],
        "auto_items": [
            {
                "id": "epic-approved",
                "store": "epic",
                "title": "Approved Epic",
                "claim_url": "https://store.epicgames.com/en-US/p/approved",
                "source": "epic",
                "ends_at": "2026-12-01T00:00:00Z",
            },
            {
                "id": "gog-hidden",
                "store": "gog",
                "title": "Hidden GOG",
                "claim_url": "https://www.gog.com/game/hidden",
                "source": "gamerpower",
            },
        ],
        "approved_ids": ["epic-approved"],
    }
    code, data = _request(base, "POST", "/api/internal/free-claims/preview", body=payload)
    assert code == 200
    items = data.get("items")
    assert isinstance(items, list)
    ids = {it["id"] for it in items}
    assert "manual-1" in ids
    assert "epic-approved" in ids
    assert "gog-hidden" not in ids
    assert not built_path.is_file()


def test_free_claims_preview_excludes_dismissed_key_matched_duplicate(
    admin_server: tuple[str, Path],
) -> None:
    """Dismissed hidden row must not re-enter preview via stale approved title key."""
    base, _ = admin_server
    payload = {
        "manual_items": [],
        "auto_items": [
            {
                "id": "epic-rogue-waters-9764d6",
                "store": "epic",
                "title": "Rogue Waters",
                "claim_url": "https://store.epicgames.com/en-US/p/rogue-waters-9764d6",
                "ends_at": "2099-01-01T00:00:00Z",
            }
        ],
        "approved_ids": ["itad-0c69ed1f1bd8"],
        "field_overrides": {"itad-0c69ed1f1bd8": {"title": "Rogue Waters"}},
        "dismissed": ["epic-rogue-waters-9764d6"],
    }
    code, data = _request(base, "POST", "/api/internal/free-claims/preview", body=payload)
    assert code == 200
    assert data.get("items") == []


def test_free_claims_preview_bypasses_supabase_auth(
    admin_server: tuple[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Internal preview must not require a Supabase JWT when BAKLOG_ADMIN=1."""
    import shared.supabase_auth as supabase_auth

    base, _ = admin_server
    monkeypatch.setattr(supabase_auth, "auth_enabled", lambda: True)
    code, data = _request(
        base,
        "POST",
        "/api/internal/free-claims/preview",
        body={"manual_items": [], "auto_items": [], "approved_ids": []},
    )
    assert code == 200
    assert isinstance(data.get("items"), list)


def test_runs_status_bypasses_supabase_auth_under_admin(
    admin_server: tuple[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The admin Jobs run-console polls /api/runs without an account JWT; under
    BAKLOG_ADMIN=1 it must not 401 when Supabase auth is enabled."""
    import shared.supabase_auth as supabase_auth

    base, _ = admin_server
    monkeypatch.setattr(supabase_auth, "auth_enabled", lambda: True)
    code, data = _request(base, "GET", "/api/runs")
    assert code == 200
    assert "history" in data


def test_unknown_internal_post_returns_404_not_401(
    admin_server: tuple[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import shared.supabase_auth as supabase_auth

    base, _ = admin_server
    monkeypatch.setattr(supabase_auth, "auth_enabled", lambda: True)
    code, _ = _request(base, "POST", "/api/internal/foo", body={})
    assert code == 404


def test_free_claims_preview_trailing_slash(
    admin_server: tuple[str, Path],
) -> None:
    base, _ = admin_server
    code, data = _request(
        base,
        "POST",
        "/api/internal/free-claims/preview/",
        body={"manual_items": [], "auto_items": [], "approved_ids": []},
    )
    assert code == 200
    assert isinstance(data.get("items"), list)
