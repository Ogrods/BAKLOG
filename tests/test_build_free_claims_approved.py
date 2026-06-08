"""Tests for opt-in approved auto-claim filtering in build_free_claims.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import build_free_claims as bfc


def test_load_approved_ids_missing_file(tmp_path: Path) -> None:
    assert bfc._load_approved_ids(tmp_path / "missing.json") == set()


def test_load_approved_ids_reads_ids(tmp_path: Path) -> None:
    path = tmp_path / "approved.json"
    path.write_text(json.dumps({"ids": ["epic-a", "gamerpower-1"]}), encoding="utf-8")
    assert bfc._load_approved_ids(path) == {"epic-a", "gamerpower-1"}


def test_load_approved_ids_ignores_bad_file(tmp_path: Path) -> None:
    path = tmp_path / "approved.json"
    path.write_text("{not json", encoding="utf-8")
    assert bfc._load_approved_ids(path) == set()


def test_infer_store_from_text_maps_itchio_giveaways() -> None:
    assert bfc._infer_store_from_text(
        "other",
        "Flufftopia (itchio) Giveaway",
        "Flufftopia is free on itch.io until June 14th 2026.",
        "https://www.gamerpower.com/open/flufftopia-itchio-giveaway",
    ) == "itch"


def test_infer_store_from_text_keeps_explicit_store() -> None:
    assert bfc._infer_store_from_text("epic", "Foo", "", "") == "epic"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-06-11T15:00:00", "2026-06-11T15:00:00Z"),       # naive → assume UTC
        ("2026-06-08T23:59:00Z", "2026-06-08T23:59:00Z"),      # already canonical
        ("2026-06-11T15:00:00-07:00", "2026-06-11T22:00:00Z"), # offset → UTC
        ("2026-06-11T15:00:00.123456+00:00", "2026-06-11T15:00:00Z"),  # drop microseconds
        (None, None),
        ("", None),
        ("not a date", "not a date"),                          # unparseable kept as-is
    ],
)
def test_normalize_ends_at(value: object, expected: str | None) -> None:
    assert bfc._normalize_ends_at(value) == expected


def test_enrich_item_normalizes_ends_at() -> None:
    out = bfc._enrich_item(
        {
            "id": "epic-foo",
            "store": "epic",
            "title": "Foo",
            "claim_url": "https://store.epicgames.com/en-US/p/foo",
            "ends_at": "2026-06-11T15:00:00-07:00",
        },
        [0.0],
    )
    assert out["ends_at"] == "2026-06-11T22:00:00Z"


def test_build_publishes_only_approved_auto_items(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "free-claims.input.json"
    auto_path = tmp_path / "free_claims.auto.json"
    approved_path = tmp_path / "free_claims.approved.json"
    output_path = tmp_path / "free-claims.json"

    input_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "manual-1",
                        "store": "steam",
                        "title": "Manual Always",
                        "claim_url": "https://store.steampowered.com/app/1",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    auto_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "epic-approved",
                        "store": "epic",
                        "title": "Approved Epic",
                        "claim_url": "https://store.epicgames.com/en-US/p/approved",
                        "source": "epic",
                    },
                    {
                        "id": "gog-hidden",
                        "store": "gog",
                        "title": "Hidden GOG",
                        "claim_url": "https://www.gog.com/game/hidden",
                        "source": "gamerpower",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    approved_path.write_text(json.dumps({"ids": ["epic-approved"]}), encoding="utf-8")

    monkeypatch.setattr(bfc, "INPUT_PATH", input_path)
    monkeypatch.setattr(bfc, "AUTO_PATH", auto_path)
    monkeypatch.setattr(bfc, "APPROVED_PATH", approved_path)
    monkeypatch.setattr(bfc, "OUTPUT_PATH", output_path)
    monkeypatch.setattr(bfc, "FALLBACK_PATH", tmp_path / "fallback.json")
    monkeypatch.setattr(bfc, "free_claims_path", lambda: tmp_path / "profile.json")
    monkeypatch.setattr(
        bfc,
        "_enrich_item",
        lambda raw, last_call, cover_lookup=None: {
            "id": raw["id"],
            "store": raw["store"],
            "title": raw["title"],
            "claim_url": raw["claim_url"],
        },
    )
    monkeypatch.setattr(sys, "argv", ["build_free_claims.py", "--no-profile"])

    assert bfc.main() == 0
    built = json.loads(output_path.read_text(encoding="utf-8"))
    ids = {item["id"] for item in built["items"]}
    assert ids == {"manual-1", "epic-approved"}


def test_build_without_approved_file_publishes_manual_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "free-claims.input.json"
    auto_path = tmp_path / "free_claims.auto.json"
    approved_path = tmp_path / "free_claims.approved.json"
    output_path = tmp_path / "free-claims.json"

    input_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "manual-only",
                        "store": "steam",
                        "title": "Manual Only",
                        "claim_url": "https://store.steampowered.com/app/2",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    auto_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "epic-unapproved",
                        "store": "epic",
                        "title": "Should Not Publish",
                        "claim_url": "https://store.epicgames.com/en-US/p/nope",
                        "source": "epic",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(bfc, "INPUT_PATH", input_path)
    monkeypatch.setattr(bfc, "AUTO_PATH", auto_path)
    monkeypatch.setattr(bfc, "APPROVED_PATH", approved_path)
    monkeypatch.setattr(bfc, "OUTPUT_PATH", output_path)
    monkeypatch.setattr(bfc, "FALLBACK_PATH", tmp_path / "fallback.json")
    monkeypatch.setattr(bfc, "free_claims_path", lambda: tmp_path / "profile.json")
    monkeypatch.setattr(
        bfc,
        "_enrich_item",
        lambda raw, last_call, cover_lookup=None: {
            "id": raw["id"],
            "store": raw["store"],
            "title": raw["title"],
            "claim_url": raw["claim_url"],
        },
    )
    monkeypatch.setattr(sys, "argv", ["build_free_claims.py", "--no-profile"])

    assert bfc.main() == 0
    built = json.loads(output_path.read_text(encoding="utf-8"))
    assert [item["id"] for item in built["items"]] == ["manual-only"]


def test_build_applies_field_overrides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "free-claims.input.json"
    auto_path = tmp_path / "free_claims.auto.json"
    approved_path = tmp_path / "free_claims.approved.json"
    output_path = tmp_path / "free-claims.json"

    input_path.write_text(json.dumps({"items": []}), encoding="utf-8")
    auto_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "epic-approved",
                        "store": "epic",
                        "title": "Original Title",
                        "claim_url": "https://store.epicgames.com/en-US/p/original",
                        "ends_at": "2099-01-01T00:00:00Z",
                        "source": "epic",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    approved_path.write_text(
        json.dumps(
            {
                "ids": ["epic-approved"],
                "field_overrides": {
                    "epic-approved": {
                        "title": "Edited Title",
                        "claim_url": "https://store.epicgames.com/en-US/p/edited",
                        "ends_at": "2099-06-01T12:00:00Z",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(bfc, "INPUT_PATH", input_path)
    monkeypatch.setattr(bfc, "AUTO_PATH", auto_path)
    monkeypatch.setattr(bfc, "APPROVED_PATH", approved_path)
    monkeypatch.setattr(bfc, "OUTPUT_PATH", output_path)
    monkeypatch.setattr(bfc, "FALLBACK_PATH", tmp_path / "fallback.json")
    monkeypatch.setattr(bfc, "free_claims_path", lambda: tmp_path / "profile.json")
    monkeypatch.setattr(
        bfc,
        "_enrich_item",
        lambda raw, last_call, cover_lookup=None: {
            "id": raw["id"],
            "store": raw["store"],
            "title": raw["title"],
            "claim_url": raw["claim_url"],
            "ends_at": raw.get("ends_at"),
        },
    )
    monkeypatch.setattr(sys, "argv", ["build_free_claims.py", "--no-profile"])

    assert bfc.main() == 0
    built = json.loads(output_path.read_text(encoding="utf-8"))
    assert len(built["items"]) == 1
    item = built["items"][0]
    assert item["title"] == "Edited Title"
    assert item["claim_url"] == "https://store.epicgames.com/en-US/p/edited"
    assert item["ends_at"] == "2099-06-01T12:00:00Z"


def test_build_prunes_expired_approved_and_manual_items(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "free-claims.input.json"
    auto_path = tmp_path / "free_claims.auto.json"
    approved_path = tmp_path / "free_claims.approved.json"
    output_path = tmp_path / "free-claims.json"

    input_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "manual-expired",
                        "store": "steam",
                        "title": "Expired Manual",
                        "claim_url": "https://store.steampowered.com/app/999",
                        "ends_at": "2020-01-01T00:00:00Z",
                    },
                    {
                        "id": "manual-live",
                        "store": "steam",
                        "title": "Live Manual",
                        "claim_url": "https://store.steampowered.com/app/1000",
                        "ends_at": "2099-01-01T00:00:00Z",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    auto_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "epic-expired",
                        "store": "epic",
                        "title": "Expired Epic",
                        "claim_url": "https://store.epicgames.com/en-US/p/expired",
                        "ends_at": "2020-01-01T00:00:00Z",
                        "source": "epic",
                    },
                    {
                        "id": "epic-live",
                        "store": "epic",
                        "title": "Live Epic",
                        "claim_url": "https://store.epicgames.com/en-US/p/live",
                        "ends_at": "2099-01-01T00:00:00Z",
                        "source": "epic",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    approved_path.write_text(
        json.dumps(
            {
                "ids": ["epic-expired", "epic-live"],
                "store_overrides": {"epic-expired": "steam"},
                "field_overrides": {"epic-expired": {"title": "Should Be Pruned"}},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(bfc, "INPUT_PATH", input_path)
    monkeypatch.setattr(bfc, "AUTO_PATH", auto_path)
    monkeypatch.setattr(bfc, "APPROVED_PATH", approved_path)
    monkeypatch.setattr(bfc, "OUTPUT_PATH", output_path)
    monkeypatch.setattr(bfc, "FALLBACK_PATH", tmp_path / "fallback.json")
    monkeypatch.setattr(bfc, "free_claims_path", lambda: tmp_path / "profile.json")
    monkeypatch.setattr(
        bfc,
        "_enrich_item",
        lambda raw, last_call, cover_lookup=None: {
            "id": raw["id"],
            "store": raw["store"],
            "title": raw["title"],
            "claim_url": raw["claim_url"],
            "ends_at": raw.get("ends_at"),
        },
    )
    monkeypatch.setattr(sys, "argv", ["build_free_claims.py", "--no-profile"])

    assert bfc.main() == 0
    built = json.loads(output_path.read_text(encoding="utf-8"))
    ids = {item["id"] for item in built["items"]}
    assert ids == {"manual-live", "epic-live"}

    approved = json.loads(approved_path.read_text(encoding="utf-8"))
    assert approved["ids"] == ["epic-live"]
    assert "epic-expired" not in (approved.get("store_overrides") or {})
    assert "epic-expired" not in (approved.get("field_overrides") or {})


def test_enrich_item_resolves_steam_appid_and_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    last_call = [0.0]
    raw = {
        "id": "gamerpower-999",
        "store": "steam",
        "title": "Portal 2 (Steam) Giveaway",
        "claim_url": "https://www.gamerpower.com/open/portal-2",
        "source": "gamerpower",
    }

    monkeypatch.setattr(
        bfc,
        "_steam_storesearch",
        lambda term, lc: [{"id": 620, "name": "Portal 2"}],
    )
    monkeypatch.setattr(
        bfc,
        "_steam_app_details",
        lambda appid, lc: {
            "name": "Portal 2",
            "header_image": "https://cdn.example/portal2.jpg",
            "genres": [{"description": "Action"}],
        },
    )
    monkeypatch.setattr(bfc, "_steam_review_percent", lambda appid, lc: 98)

    out = bfc._enrich_item(raw, last_call)

    assert out["id"] == "gamerpower-999"
    assert out["steam_appid"] == 620
    assert out["review_percent"] == 98
    assert out["header_image"] == bfc._steam_portrait_cover(620)
    assert out["genres"] == ["Action"]


def test_enrich_item_keeps_dash_when_no_appid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    last_call = [0.0]
    raw = {
        "id": "gamerpower-888",
        "store": "steam",
        "title": "Unknown Obscure Title (Steam) Giveaway",
        "claim_url": "https://www.gamerpower.com/open/obscure",
    }

    monkeypatch.setattr(bfc, "_steam_storesearch", lambda term, lc: [])
    monkeypatch.setattr(bfc, "_resolve_steam_appid", lambda **kwargs: None)

    out = bfc._enrich_item(raw, last_call)

    assert out["id"] == "gamerpower-888"
    assert "steam_appid" not in out
    assert "review_percent" not in out


def test_enrich_item_resolves_steam_cover_for_non_steam_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = {
        "id": "itad-b07aac9ebd26",
        "store": "epic",
        "title": "Wytchwood free for mobile on EGS on Epic Game Store",
        "claim_url": "https://isthereanydeal.com/giveaways/16242/",
        "header_image": None,
        "source": "itad",
    }
    monkeypatch.setattr(
        bfc,
        "_steam_storesearch",
        lambda term, lc: [{"id": 1016800, "name": "Wytchwood"}],
    )
    monkeypatch.setattr(
        bfc,
        "_steam_app_details",
        lambda appid, lc: {
            "name": "Wytchwood",
            "header_image": "https://cdn.example/wytchwood.jpg",
            "genres": [{"description": "Adventure"}],
        },
    )
    monkeypatch.setattr(bfc, "_steam_review_percent", lambda appid, lc: 91)

    out = bfc._enrich_item(raw, [0.0])

    assert out["store"] == "epic"
    assert out["steam_appid"] == 1016800
    assert out["header_image"] == bfc._steam_portrait_cover(1016800)
    assert out["review_percent"] == 91
    assert out["genres"] == []


def test_enrich_item_upgrades_gamerpower_cover_to_portrait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = {
        "id": "gamerpower-2386",
        "store": "steam",
        "title": "Tell Me Why (Steam) Giveaway",
        "claim_url": "https://www.gamerpower.com/open/tell-me-why-steam-giveaway",
        "header_image": "https://www.gamerpower.com/offers/1b/6478b9dcae7be.jpg",
        "source": "gamerpower",
    }
    monkeypatch.setattr(
        bfc,
        "_steam_storesearch",
        lambda term, lc: [{"id": 1180660, "name": "Tell Me Why"}],
    )
    monkeypatch.setattr(
        bfc,
        "_steam_app_details",
        lambda appid, lc: {"name": "Tell Me Why", "genres": []},
    )
    monkeypatch.setattr(bfc, "_steam_review_percent", lambda appid, lc: 82)

    out = bfc._enrich_item(raw, [0.0])

    assert out["steam_appid"] == 1180660
    assert out["header_image"] == bfc._steam_portrait_cover(1180660)
    assert "gamerpower.com" not in (out["header_image"] or "")


def test_enrich_item_borrows_cover_from_sibling_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bfc, "_resolve_steam_appid_by_title", lambda title, lc: None)
    lookup = bfc._build_cover_lookup(
        [
            {
                "id": "gamerpower-3096",
                "title": "Madness Inside (itch.io) Giveaway",
                "header_image": "https://www.gamerpower.com/offers/madness.jpg",
            }
        ]
    )
    raw = {
        "id": "itad-d85d5bb4128d",
        "store": "itch",
        "title": "Madness Inside free on itchio on Itch.io",
        "claim_url": "https://isthereanydeal.com/giveaways/15895/",
        "header_image": None,
        "source": "itad",
    }
    out = bfc._enrich_item(raw, [0.0], lookup)
    assert out["header_image"] == "https://www.gamerpower.com/offers/madness.jpg"


def test_resolve_steam_appid_from_itad_blurb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bfc, "_steam_storesearch", lambda term, lc: [])
    appid = bfc._resolve_steam_appid(
        store="steam",
        title="Gravity Circuit free on Steam on Steam",
        claim_url="https://isthereanydeal.com/giveaways/16228/",
        blurb='go to <a href="https://store.steampowered.com/app/858710/Gravity_Circuit/">giveaway</a>',
        last_call=[0.0],
    )
    assert appid == 858710


def test_preview_publish_items_merges_without_network() -> None:
    from datetime import UTC, datetime

    now = datetime(2026, 6, 8, 12, 0, 0, tzinfo=UTC)
    items = bfc.preview_publish_items(
        manual_items=[
            {
                "id": "manual-1",
                "store": "steam",
                "title": "Manual",
                "claim_url": "https://store.steampowered.com/app/1",
            }
        ],
        auto_items_all=[
            {
                "id": "epic-ok",
                "store": "epic",
                "title": "Epic Game",
                "claim_url": "https://store.epicgames.com/en-US/p/ok",
                "ends_at": "2026-12-01T00:00:00Z",
            },
            {
                "id": "epic-old",
                "store": "epic",
                "title": "Expired",
                "claim_url": "https://store.epicgames.com/en-US/p/old",
                "ends_at": "2026-05-01T00:00:00Z",
            },
        ],
        approved_ids={"epic-ok"},
        now=now,
    )
    ids = {it["id"] for it in items}
    assert ids == {"manual-1", "epic-ok"}
    assert all(it.get("claim_url") and it.get("store") for it in items)
