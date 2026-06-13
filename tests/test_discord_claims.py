"""Tests for Discord claim announcements (shared/discord_claims.py)."""

from __future__ import annotations

import io
import json
import urllib.error
from unittest.mock import patch

import pytest

from shared.discord_claims import (
    CLAIM_LINK,
    _post_webhook_once,
    build_discord_payload,
    load_webhooks,
    post_claim_to_discord,
    post_to_webhook,
    validate_claim_item_for_discord,
)


def test_validate_claim_item_for_discord_requires_core_fields() -> None:
    assert validate_claim_item_for_discord({}) == "item missing id"
    assert validate_claim_item_for_discord({"id": "x"}) == "item missing store"
    assert validate_claim_item_for_discord({"id": "x", "store": "steam"}) == "item missing title"
    assert validate_claim_item_for_discord(
        {"id": "x", "store": "steam", "title": "Portal 2"}
    ) is None


def test_build_discord_payload_shape() -> None:
    payload = build_discord_payload(
        {
            "id": "epic-1",
            "store": "epic",
            "title": "Portal 2",
            "header_image": "https://cdn.example/cover.jpg",
            "ends_at": "2026-06-18T15:00:00Z",
            "source": "epic",
        }
    )
    assert CLAIM_LINK in payload["content"]
    embed = payload["embeds"][0]
    assert embed["title"] == "Portal 2"
    assert embed["url"] == CLAIM_LINK
    assert embed["thumbnail"]["url"] == "https://cdn.example/cover.jpg"
    field_names = {f["name"] for f in embed["fields"]}
    assert field_names == {"Store", "Ends"}
    assert "footer" not in embed


def test_build_discord_payload_uses_claim_url() -> None:
    payload = build_discord_payload(
        {
            "id": "epic-1",
            "store": "epic",
            "title": "Portal 2",
            "claim_url": "https://store.epicgames.com/p/portal-2",
        }
    )
    embed = payload["embeds"][0]
    assert embed["url"] == "https://store.epicgames.com/p/portal-2"
    assert "https://store.epicgames.com/p/portal-2" in payload["content"]
    assert CLAIM_LINK not in payload["content"]


def test_build_discord_payload_beta_invite_adds_copy() -> None:
    payload = build_discord_payload(
        {
            "id": "epic-1",
            "store": "epic",
            "title": "Portal 2",
            "claim_url": "https://store.epicgames.com/p/portal-2",
        },
        include_beta_invite=True,
    )
    assert "https://store.epicgames.com/p/portal-2" in payload["content"]
    assert "closed beta" in payload["content"]
    assert CLAIM_LINK in payload["content"]


def test_build_discord_payload_ignores_non_http_claim_url() -> None:
    payload = build_discord_payload(
        {"id": "x", "store": "steam", "title": "Foo", "claim_url": "javascript:alert(1)"}
    )
    assert payload["embeds"][0]["url"] == CLAIM_LINK


def test_post_claim_to_discord_varies_content_per_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BAKLOG_DISCORD_CLAIMS_WEBHOOK_1", "https://discord.example/altar")
    monkeypatch.setenv("BAKLOG_DISCORD_CLAIMS_WEBHOOK_2", "https://discord.example/members")
    bodies: dict[str, dict] = {}

    def fake_post(url: str, body: dict) -> dict:
        bodies[url] = body
        return {"ok": True, "status": 204}

    with patch("shared.discord_claims.post_to_webhook", side_effect=fake_post):
        post_claim_to_discord(
            {
                "id": "x",
                "store": "steam",
                "title": "Foo",
                "claim_url": "https://store.steampowered.com/app/620",
            }
        )
    altar = bodies["https://discord.example/altar"]["content"]
    members = bodies["https://discord.example/members"]["content"]
    assert "closed beta" in altar
    assert "closed beta" not in members
    assert "https://store.steampowered.com/app/620" in altar
    assert "https://store.steampowered.com/app/620" in members


def test_build_discord_payload_strips_giveaway_title() -> None:
    payload = build_discord_payload(
        {
            "id": "gp-1",
            "store": "steam",
            "title": "Portal 2 (Steam) Giveaway",
            "source": "gamerpower",
        }
    )
    embed = payload["embeds"][0]
    assert embed["title"] == "Portal 2"
    assert embed["footer"]["text"] == "GamerPower.com"


def test_build_discord_payload_omits_ends_when_missing() -> None:
    payload = build_discord_payload(
        {"id": "x", "store": "steam", "title": "Foo", "ends_at": None}
    )
    field_names = [f["name"] for f in payload["embeds"][0]["fields"]]
    assert field_names == ["Store"]


def test_load_webhooks_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BAKLOG_DISCORD_CLAIMS_WEBHOOK_1", "https://discord.example/one")
    monkeypatch.setenv("BAKLOG_DISCORD_CLAIMS_WEBHOOK_2", "  ")
    monkeypatch.delenv("BAKLOG_DISCORD_CLAIMS_WEBHOOK_2", raising=False)
    hooks = load_webhooks()
    assert hooks == [{"name": "Sacrificial Altar", "url": "https://discord.example/one"}]


def test_post_claim_to_discord_posts_to_each_webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BAKLOG_DISCORD_CLAIMS_WEBHOOK_1", "https://discord.example/one")
    monkeypatch.setenv("BAKLOG_DISCORD_CLAIMS_WEBHOOK_2", "https://discord.example/two")
    calls: list[str] = []

    def fake_post(url: str, body: dict) -> dict:
        calls.append(url)
        return {"ok": True, "status": 204}

    with patch("shared.discord_claims.post_to_webhook", side_effect=fake_post):
        results = post_claim_to_discord(
            {"id": "x", "store": "steam", "title": "Foo", "source": "epic"}
        )
    assert len(results) == 2
    assert all(row["ok"] for row in results)
    assert calls == ["https://discord.example/one", "https://discord.example/two"]


def test_post_to_webhook_retries_on_429() -> None:
    body = build_discord_payload({"id": "x", "store": "steam", "title": "Foo"})
    rate_body = json.dumps({"retry_after": 0.01}).encode()
    success_response = type(
        "Resp",
        (),
        {
            "status": 204,
            "read": lambda self: b"",
            "__enter__": lambda self: self,
            "__exit__": lambda self, *args: None,
        },
    )()

    def urlopen_side_effect(req, timeout=30):
        if not hasattr(urlopen_side_effect, "calls"):
            urlopen_side_effect.calls = 0
        urlopen_side_effect.calls += 1
        if urlopen_side_effect.calls == 1:
            raise urllib.error.HTTPError(
                req.full_url,
                429,
                "Too Many Requests",
                hdrs={},
                fp=io.BytesIO(rate_body),
            )
        return success_response

    with patch("shared.discord_claims.time.sleep"), patch(
        "urllib.request.urlopen", side_effect=urlopen_side_effect
    ):
        result = post_to_webhook("https://discord.example/hook", body)

    assert result["ok"] is True
    assert urlopen_side_effect.calls == 2


def test_post_webhook_once_handles_urlerror() -> None:
    body = build_discord_payload({"id": "x", "store": "steam", "title": "Foo"})
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.URLError("connection refused"),
    ):
        status, detail, retry_after, rate_limit_global = _post_webhook_once("https://discord.example/hook", body)
    assert status == 0
    assert "network error" in detail
    assert retry_after is None
    assert rate_limit_global is False


def test_post_webhook_once_handles_timeout() -> None:
    body = build_discord_payload({"id": "x", "store": "steam", "title": "Foo"})
    with patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
        status, detail, retry_after, rate_limit_global = _post_webhook_once("https://discord.example/hook", body)
    assert status == 0
    assert "network error" in detail
    assert retry_after is None
    assert rate_limit_global is False


def test_post_to_webhook_returns_failure_on_network_error() -> None:
    body = build_discord_payload({"id": "x", "store": "steam", "title": "Foo"})
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.URLError("name not resolved"),
    ):
        result = post_to_webhook("https://discord.example/hook", body)
    assert result["ok"] is False
    assert result["status"] == 0
    assert "network error" in result["error"]


def test_post_claim_to_discord_structured_failure_on_network_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BAKLOG_DISCORD_CLAIMS_WEBHOOK_1", "https://discord.example/one")
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.URLError("connection refused"),
    ):
        results = post_claim_to_discord(
            {"id": "x", "store": "steam", "title": "Foo", "source": "epic"}
        )
    assert len(results) == 1
    assert results[0]["ok"] is False
    assert results[0]["name"] == "Sacrificial Altar"
    assert "network error" in results[0]["error"]


def test_build_discord_payload_clamps_long_ends_field() -> None:
    long_ends = "x" * 2000
    payload = build_discord_payload(
        {"id": "x", "store": "steam", "title": "Foo", "ends_at": long_ends}
    )
    ends_field = next(f for f in payload["embeds"][0]["fields"] if f["name"] == "Ends")
    assert len(ends_field["value"]) == 1024


def test_load_webhooks_skips_non_http_scheme(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BAKLOG_DISCORD_CLAIMS_WEBHOOK_1", "ftp://discord.example/bad")
    monkeypatch.setenv("BAKLOG_DISCORD_CLAIMS_WEBHOOK_2", "https://discord.example/good")
    hooks = load_webhooks()
    assert hooks == [{"name": "BAKLOG Discord", "url": "https://discord.example/good"}]


def test_post_to_webhook_stops_on_large_retry_after() -> None:
    body = build_discord_payload({"id": "x", "store": "steam", "title": "Foo"})
    rate_body = json.dumps({"retry_after": 60.0, "global": False}).encode()
    sleeps: list[float] = []

    def urlopen_side_effect(req, timeout=30):
        raise urllib.error.HTTPError(
            req.full_url,
            429,
            "Too Many Requests",
            hdrs={},
            fp=io.BytesIO(rate_body),
        )

    with patch("shared.discord_claims.time.sleep", side_effect=lambda s: sleeps.append(s)), patch(
        "urllib.request.urlopen", side_effect=urlopen_side_effect
    ):
        result = post_to_webhook("https://discord.example/hook", body)

    assert result["ok"] is False
    assert result["status"] == 429
    assert sleeps == []


def test_post_to_webhook_stops_on_global_rate_limit() -> None:
    body = build_discord_payload({"id": "x", "store": "steam", "title": "Foo"})
    rate_body = json.dumps({"retry_after": 0.5, "global": True}).encode()
    sleeps: list[float] = []

    def urlopen_side_effect(req, timeout=30):
        raise urllib.error.HTTPError(
            req.full_url,
            429,
            "Too Many Requests",
            hdrs={},
            fp=io.BytesIO(rate_body),
        )

    with patch("shared.discord_claims.time.sleep", side_effect=lambda s: sleeps.append(s)), patch(
        "urllib.request.urlopen", side_effect=urlopen_side_effect
    ):
        result = post_to_webhook("https://discord.example/hook", body)

    assert result["ok"] is False
    assert result["status"] == 429
    assert sleeps == []
