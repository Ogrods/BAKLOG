from unittest.mock import MagicMock, patch

import pytest
import requests

from clients.gog_client import GOG_AUTH_MESSAGE, GogAuthError, GogClient


@pytest.fixture()
def client(tmp_path):
    return GogClient(gog_al="test-session", cache_dir=tmp_path / "gog")


def _mock_response(status_code, json_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(f"{status_code}", response=resp)
    else:
        resp.raise_for_status.return_value = None
    return resp


class TestGogAuthErrors:
    def test_get_filtered_products_403_raises_gog_auth_error(self, client):
        with patch.object(client.session, "get", return_value=_mock_response(403)):
            with pytest.raises(GogAuthError) as exc:
                client.get_filtered_products(page=1, refresh=True)
        assert GOG_AUTH_MESSAGE in str(exc.value)

    def test_get_filtered_products_401_raises_gog_auth_error(self, client):
        with patch.object(client.session, "get", return_value=_mock_response(401)):
            with pytest.raises(GogAuthError):
                client.get_owned_game_ids()

    def test_get_uses_browser_like_headers(self, client):
        assert "www.gog.com" in client.session.headers["Referer"]
        assert "www.gog.com" in client.session.headers["Origin"]
        assert "Chrome" in client.session.headers["User-Agent"]


class TestValidateSession:
    def test_validate_session_accepts_owned_ids_when_library_403(self, client):
        calls = []

        def fake_get(url, timeout=30):
            calls.append(url)
            if url.endswith("/userData.json"):
                return _mock_response(200, {"username": "u"})
            if "getFilteredProducts" in url:
                return _mock_response(403)
            if "/user/data/games" in url:
                return _mock_response(200, {"owned": [101, 202]})
            return _mock_response(404)

        with patch.object(client.session, "get", side_effect=fake_get):
            assert client.validate_session() is True
        assert any("userData.json" in u for u in calls)
        assert any("getFilteredProducts" in u for u in calls)
        assert any("/user/data/games" in u for u in calls)

    def test_validate_session_fails_when_library_and_owned_blocked(self, client):

        def fake_get(url, timeout=30):
            if url.endswith("/userData.json"):
                return _mock_response(200, {"username": "u"})
            if "getFilteredProducts" in url or "/user/data/games" in url:
                return _mock_response(403)
            return _mock_response(404)

        with patch.object(client.session, "get", side_effect=fake_get):
            with pytest.raises(GogAuthError):
                client.validate_session()

    def test_validate_session_succeeds_when_library_probe_ok(self, client):

        def fake_get(url, timeout=30):
            if url.endswith("/userData.json"):
                return _mock_response(200, {"username": "u"})
            if "getFilteredProducts" in url:
                return _mock_response(200, {"products": [{"id": 1, "title": "Game"}], "totalPages": 1})
            return _mock_response(404)

        with patch.object(client.session, "get", side_effect=fake_get):
            assert client.validate_session() is True
