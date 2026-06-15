"""Unit tests for Prime Gaming web claim filtering (no browser)."""

from __future__ import annotations

from clients.amazon_web_client import (
    _CODE_FIELD_NAMES,
    _capture_claims_from_response,
    _drain_claim_candidates,
    claim_to_record,
    extract_claims_list,
    filter_codeless_claims,
    is_codeless_claim,
    scrub_claim_codes,
    try_parse_claims_from_text,
)


def test_scrub_claim_codes_removes_credential_fields():
    claims = [
        {
            "itemTitle": "Game",
            "itemId": "id-1",
            "redemptionCode": "AAAA-BBBB",
            "gameCode": "CCCC",
            "claimCode": "DDDD",
            "activationCode": "EEEE",
            "code": "FFFF",
        }
    ]
    out = scrub_claim_codes(claims)
    assert out[0]["itemTitle"] == "Game"
    assert out[0]["itemId"] == "id-1"
    for field in _CODE_FIELD_NAMES:
        assert field not in out[0]
    # The input claim must not be mutated in place.
    assert claims[0]["redemptionCode"] == "AAAA-BBBB"


def test_scrub_claim_codes_passes_through_non_dicts():
    assert scrub_claim_codes([{"itemId": "x"}, "junk", 5]) == [{"itemId": "x"}, "junk", 5]


class _FakeResponse:
    """Minimal CDP-style response. Reading the body is only allowed off the
    reader thread, so .text() flags any call made from inside the handler."""

    def __init__(self, url: str, status: int, body: str) -> None:
        self.url = url
        self.status = status
        self._body = body
        self.text_calls = 0

    def text(self) -> str:
        self.text_calls += 1
        return self._body


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


def test_capture_handler_never_reads_body_on_reader_thread():
    # Regression: reading resp.text() inside the response handler deadlocks the
    # single CDP reader thread. The handler must only enqueue candidates.
    resp = _FakeResponse(
        "https://luna.amazon.com/graphql",
        200,
        '{"data":{"claims":{"claims":[{"itemTitle":"X","itemId":"y"}]}}}',
    )
    candidates: list = []
    raw_claims: list[dict] = []
    captured = {"done": False}

    _capture_claims_from_response(resp, candidates, raw_claims, captured)

    assert resp.text_calls == 0
    assert candidates == [resp]
    assert captured["done"] is False
    assert raw_claims == []


def test_capture_handler_ignores_non_claim_and_non_200_responses():
    candidates: list = []
    raw_claims: list[dict] = []
    captured = {"done": False}

    _capture_claims_from_response(
        _FakeResponse("https://luna.amazon.com/static/app.js", 200, ""),
        candidates, raw_claims, captured,
    )
    _capture_claims_from_response(
        _FakeResponse("https://luna.amazon.com/graphql", 500, ""),
        candidates, raw_claims, captured,
    )

    assert candidates == []


def test_drain_candidates_captures_claims_off_reader_thread():
    resp = _FakeResponse(
        "https://luna.amazon.com/graphql",
        200,
        '{"data":{"claims":{"claims":[{"itemTitle":"X","itemId":"y"}]}}}',
    )
    candidates: list = [resp]
    raw_claims: list[dict] = []
    captured = {"done": False}

    done = _drain_claim_candidates(candidates, raw_claims, captured)

    assert done is True
    assert captured["done"] is True
    assert resp.text_calls == 1
    assert len(raw_claims) == 1
    assert raw_claims[0]["itemTitle"] == "X"
    assert candidates == []


def test_drain_candidates_empty_claims_payload_counts_as_capture():
    resp = _FakeResponse(
        "https://luna.amazon.com/graphql",
        200,
        '{"data":{"claims":{"claims":[]}}}',
    )
    captured = {"done": False}
    raw_claims: list[dict] = []

    assert _drain_claim_candidates([resp], raw_claims, captured) is True
    assert captured["done"] is True
    assert raw_claims == []


def test_drain_candidates_skips_unparseable_then_keeps_polling():
    bad = _FakeResponse("https://luna.amazon.com/graphql", 200, "<html>not json</html>")
    candidates: list = [bad]
    captured = {"done": False}
    raw_claims: list[dict] = []

    # Unparseable body is consumed but does not capture; loop stays open.
    assert _drain_claim_candidates(candidates, raw_claims, captured) is False
    assert captured["done"] is False
    assert candidates == []
