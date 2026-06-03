"""Unit tests for Prime Gaming web claim filtering (no browser)."""

from __future__ import annotations

from amazon_web_client import (
    claim_to_record,
    extract_claims_list,
    filter_codeless_claims,
    is_codeless_claim,
    try_parse_claims_from_text,
)


def test_extract_claims_list_nested_shape():
    payload = {
        "data": {
            "claims": {
                "claims": [
                    {"itemTitle": "Alpha", "itemId": "amzn1.pg.item.aaa"},
                ]
            }
        }
    }
    items = extract_claims_list(payload)
    assert items is not None
    assert len(items) == 1
    assert items[0]["itemTitle"] == "Alpha"


def test_is_codeless_claim_rejects_epic_key_drop():
    claim = {
        "itemTitle": "Tomb Raider IV-VI Remastered",
        "itemId": "amzn1.pg.item.cba06ec0",
        "destinationAccountType": "EPIC",
        "destinationAccount": "player1",
    }
    assert is_codeless_claim(claim) is False
    assert claim_to_record(claim) is None


def test_is_codeless_claim_rejects_redemption_code_field():
    claim = {
        "itemTitle": "Some Game",
        "itemId": "amzn1.pg.item.x",
        "redemptionCode": "AAAA-BBBB",
    }
    assert is_codeless_claim(claim) is False


def test_is_codeless_claim_accepts_amazon_fulfilled():
    claim = {
        "itemTitle": "Lake",
        "itemId": "amzn1.pg.item.lake",
        "orderId": "amzn1.pg.order.1",
        "orderState": "FULFILLED",
    }
    assert is_codeless_claim(claim) is True
    rec = claim_to_record(claim)
    assert rec is not None
    assert rec["name"] == "Lake"
    assert rec["amazon_product_id"] == "amzn1.pg.item.lake"
    assert rec["product_line"] == "prime_claim"


def test_is_codeless_claim_rejects_missing_title():
    assert is_codeless_claim({"itemId": "x", "destinationAccountType": ""}) is False


def test_filter_codeless_dedupes_by_product_id():
    claims = [
        {"itemTitle": "A", "itemId": "id-1"},
        {"itemTitle": "A duplicate", "itemId": "id-1"},
        {"itemTitle": "B", "itemId": "id-2"},
    ]
    out = filter_codeless_claims(claims)
    assert len(out) == 2
    assert [r["name"] for r in out] == ["A", "B"]


def test_try_parse_claims_from_text():
    body = '{"data":{"claims":{"claims":[{"itemTitle":"X","itemId":"y"}]}}}'
    parsed = try_parse_claims_from_text(body)
    assert parsed is not None
    assert len(parsed) == 1
