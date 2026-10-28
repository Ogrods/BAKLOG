"""Tests for Steam store API retry behavior."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from clients.steam_client import SteamClient, _get_with_retry


def test_get_with_retry_succeeds_after_connection_errors() -> None:
    ok = MagicMock()
    ok.status_code = 200
    ok.raise_for_status = MagicMock()
    errors = [requests.ConnectionError("dns"), requests.ConnectionError("dns"), ok]
    with patch("clients.steam_client.requests.get", side_effect=errors) as get:
        with patch("clients.steam_client.time.sleep"):
            resp = _get_with_retry("https://store.steampowered.com/api/appdetails", {"appids": 1})
    assert resp is ok
    assert get.call_count == 3


def test_get_with_retry_succeeds_after_retryable_http_status() -> None:
    throttled = MagicMock()
    throttled.status_code = 429
    throttled.raise_for_status = MagicMock()
    ok = MagicMock()
    ok.status_code = 200
    ok.raise_for_status = MagicMock()
    with patch("clients.steam_client.requests.get", side_effect=[throttled, ok]) as get:
        with patch("clients.steam_client.time.sleep") as sleep:
            resp = _get_with_retry("https://store.steampowered.com/api/appdetails", {"appids": 1})
    assert resp is ok
    assert get.call_count == 2
    sleep.assert_called_once()
    # The first (429) response is retried, not raised.
    throttled.raise_for_status.assert_not_called()


def test_get_with_retry_raises_after_persistent_retryable_status() -> None:
    throttled = MagicMock()
    throttled.status_code = 503
    throttled.raise_for_status = MagicMock(
        side_effect=requests.HTTPError("503", response=throttled)
    )
    with patch("clients.steam_client.requests.get", return_value=throttled) as get:
        with patch("clients.steam_client.time.sleep"):
            with pytest.raises(requests.HTTPError):
                _get_with_retry(
                    "https://store.steampowered.com/api/appdetails",
                    {"appids": 1},
                    retries=2,
                )
    assert get.call_count == 2


def test_get_with_retry_raises_after_exhausted_retries() -> None:
    with patch("clients.steam_client.requests.get", side_effect=requests.ConnectionError("dns")) as get:
        with patch("clients.steam_client.time.sleep"):
            with pytest.raises(requests.ConnectionError):
                _get_with_retry(
                    "https://store.steampowered.com/api/appdetails",
                    {"appids": 1},
                    retries=2,
                )
    assert get.call_count == 2


def test_get_app_details_uses_retry(tmp_path) -> None:
    client = SteamClient("key", "76561198000000000", cache_dir=tmp_path)
    ok = MagicMock()
    ok.status_code = 200
    ok.json.return_value = {"70": {"success": True, "data": {"type": "game", "name": "Half-Life"}}}
    ok.raise_for_status = MagicMock()
    # Patch the globals SteamClient actually resolves: other tests pop
    # clients.steam_client from sys.modules, so a dotted-path patch can miss.
    fake_get = MagicMock(return_value=ok)
    with patch.dict(SteamClient.get_app_details.__globals__, {"_get_with_retry": fake_get}):
        with patch.object(SteamClient, "_throttle_store"):
            result = client.get_app_details(70, refresh=True)
    fake_get.assert_called_once()
    assert result is not None
    assert result["success"] is True
    assert result["data"]["name"] == "Half-Life"


def test_review_summary_from_payload_unwraps_response_envelope() -> None:
    from clients.steam_client import review_summary_from_payload

    result = review_summary_from_payload(
        {
            "response": {
                "query_summary": {
                    "total_reviews": 100,
                    "total_positive": 95,
                    "total_negative": 5,
                    "review_score": 9,
                    "review_score_desc": "Overwhelmingly Positive",
                }
            }
        }
    )
    assert result["percent_positive"] == 95.0
    assert result["total_reviews"] == 100
    assert result["review_score_desc"] == "Overwhelmingly Positive"


def test_review_summary_from_payload_empty_summary() -> None:
    from clients.steam_client import review_summary_from_payload

    result = review_summary_from_payload({"response": {}})
    assert result["percent_positive"] is None
    assert result["total_reviews"] == 0


def test_get_review_summary_uses_get_app_reviews(tmp_path) -> None:
    from clients import steam_client as sc

    client = SteamClient("key", "76561198000000000", cache_dir=tmp_path)
    ok = MagicMock()
    ok.status_code = 200
    ok.headers = {"content-type": "application/json"}
    ok.url = sc._GET_APP_REVIEWS_URL
    ok.text = '{"response":{"query_summary":{"total_reviews":10,"total_positive":9,"total_negative":1,"review_score":8,"review_score_desc":"Very Positive"}}}'
    ok.json.return_value = {
        "response": {
            "query_summary": {
                "total_reviews": 10,
                "total_positive": 9,
                "total_negative": 1,
                "review_score": 8,
                "review_score_desc": "Very Positive",
            }
        }
    }
    ok.raise_for_status = MagicMock()
    with patch("clients.steam_client.requests.get", return_value=ok) as get:
        with patch.object(SteamClient, "_throttle_store"):
            result = client.get_review_summary(570, refresh=True)
    assert result is not None
    assert result["percent_positive"] == 90.0
    assert get.call_count == 1
    called_url = get.call_args.args[0]
    assert "IUserReviewsService/GetAppReviews" in called_url
    params = get.call_args.kwargs.get("params") or get.call_args.args[1]
    assert "input_json" in params
    assert params.get("key") == "key"


def test_parse_json_object_rejects_html() -> None:
    from clients.steam_client import _parse_json_object

    resp = MagicMock()
    resp.headers = {"content-type": "text/html; charset=UTF-8"}
    resp.text = "<!DOCTYPE html><html></html>"
    resp.url = "https://store.steampowered.com/appreviews/1"
    with pytest.raises(ValueError, match="HTML"):
        _parse_json_object(resp)


def test_query_summary_present() -> None:
    from clients.steam_client import query_summary_present

    assert query_summary_present({"response": {"query_summary": {}}}) is True
    assert query_summary_present({"response": {}}) is False
    assert query_summary_present({"query_summary": {"total_reviews": 0}}) is True


def test_get_review_summary_does_not_cache_empty_envelope(tmp_path) -> None:
    client = SteamClient("key", "76561198000000000", cache_dir=tmp_path)
    ok = MagicMock()
    ok.status_code = 200
    ok.headers = {"content-type": "application/json"}
    ok.url = "https://api.steampowered.com/IUserReviewsService/GetAppReviews/v1/"
    ok.text = '{"response":{}}'
    ok.json.return_value = {"response": {}}
    ok.raise_for_status = MagicMock()
    with patch("clients.steam_client.requests.get", return_value=ok):
        with patch.object(SteamClient, "_throttle_store"):
            result = client.get_review_summary(1, refresh=True)
    assert result is not None
    assert result["percent_positive"] is None
    assert not (tmp_path / "reviews" / "1.json").exists()


def test_get_review_summary_caches_zero_review_summary(tmp_path) -> None:
    client = SteamClient("key", "76561198000000000", cache_dir=tmp_path)
    ok = MagicMock()
    ok.status_code = 200
    ok.headers = {"content-type": "application/json"}
    ok.url = "https://api.steampowered.com/IUserReviewsService/GetAppReviews/v1/"
    ok.text = '{"response":{"query_summary":{"total_reviews":0,"total_positive":0,"total_negative":0}}}'
    ok.json.return_value = {
        "response": {
            "query_summary": {
                "total_reviews": 0,
                "total_positive": 0,
                "total_negative": 0,
                "review_score": 0,
                "review_score_desc": "",
            }
        }
    }
    ok.raise_for_status = MagicMock()
    with patch("clients.steam_client.requests.get", return_value=ok):
        with patch.object(SteamClient, "_throttle_store"):
            result = client.get_review_summary(2, refresh=True)
    assert result["percent_positive"] is None
    assert (tmp_path / "reviews" / "2.json").exists()


def test_read_cache_soft_fails_corrupt_json(tmp_path) -> None:
    client = SteamClient("key", "76561198000000000", cache_dir=tmp_path)
    path = tmp_path / "reviews" / "3.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not-json", encoding="utf-8")
    assert client._read_cache("reviews", "3") is None
    assert not path.exists()
