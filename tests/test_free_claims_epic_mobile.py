"""Epic mobile free-claim link validation and build publish."""

from __future__ import annotations

import json
from pathlib import Path

from fetchers.build_free_claims import _infer_store_from_text, preview_publish_items
from shared.free_claims_sources import (
    has_valid_claim_links,
    item_missing_link_fields,
    normalize_claim_urls,
)
from shared.server_internal_routes import validate_free_claims_payload


def test_normalize_claim_urls_filters_bad_schemes():
    urls = normalize_claim_urls({
        "ios": "https://apps.apple.com/app/id1",
        "android": "javascript:alert(1)",
    })
    assert urls == {"ios": "https://apps.apple.com/app/id1"}


def test_has_valid_claim_links_epic_mobile():
    assert has_valid_claim_links({
        "store": "epic_mobile",
        "claim_urls": {"android": "https://play.google.com/store/apps/details?id=x"},
    })
    assert not has_valid_claim_links({"store": "epic_mobile", "claim_urls": {}})
    assert has_valid_claim_links({"store": "epic", "claim_url": "https://store.epicgames.com/x"})


def test_item_missing_link_fields():
    assert item_missing_link_fields({"store": "epic_mobile"}) == ["claim_urls"]
    assert item_missing_link_fields({"store": "epic"}) == ["claim_url"]


def test_validate_free_claims_payload_epic_mobile():
    ok = {
        "items": [{
            "id": "epic_mobile-northgard",
            "store": "epic_mobile",
            "title": "Northgard",
            "claim_urls": {
                "ios": "https://apps.apple.com/app/id123",
                "android": "https://play.google.com/store/apps/details?id=abc",
            },
        }],
    }
    assert validate_free_claims_payload(ok) is None

    bad = {
        "items": [{
            "id": "epic_mobile-empty",
            "store": "epic_mobile",
            "title": "Empty",
        }],
    }
    assert "claim_urls" in (validate_free_claims_payload(bad) or "")


def test_infer_store_from_text_mobile_epic():
    store = _infer_store_from_text(
        "epic",
        "TMNT free on Mobile from EGS on Epic Game Store",
        None,
        "https://isthereanydeal.com/giveaways/1/",
    )
    assert store == "epic_mobile"


def test_preview_publish_items_epic_mobile_manual(tmp_path: Path, monkeypatch):
    input_path = tmp_path / "free-claims.input.json"
    input_path.write_text(json.dumps({
        "items": [{
            "id": "epic_mobile-test-game",
            "store": "epic_mobile",
            "title": "Test Game",
            "claim_urls": {
                "ios": "https://apps.apple.com/app/id1",
                "android": "https://play.google.com/store/apps/details?id=tg",
            },
            "approved": True,
        }],
    }), encoding="utf-8")
    auto_path = tmp_path / "free_claims.auto.json"
    auto_path.write_text(json.dumps({"items": []}), encoding="utf-8")
    approved_path = tmp_path / "free_claims.approved.json"
    approved_path.write_text(json.dumps({"ids": []}), encoding="utf-8")

    monkeypatch.setattr("fetchers.build_free_claims.INPUT_PATH", input_path)
    monkeypatch.setattr("fetchers.build_free_claims.AUTO_PATH", auto_path)
    monkeypatch.setattr("fetchers.build_free_claims.APPROVED_PATH", approved_path)

    manual = json.loads(input_path.read_text(encoding="utf-8"))["items"]
    items = preview_publish_items(
        manual_items=manual,
        auto_items_all=[],
        approved_ids=set(),
    )
    assert len(items) == 1
    row = items[0]
    assert row["store"] == "epic_mobile"
    assert row["claim_urls"]["ios"].startswith("https://apps.apple.com/")
    assert "claim_url" not in row
