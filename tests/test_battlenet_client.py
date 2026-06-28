from unittest.mock import MagicMock, patch

import pytest

from clients.battlenet_client import ACCOUNT_URL, BattleNetAuthError, BattleNetClient, probe_session


def test_xsrf_token_header_from_cookie():
    client = BattleNetClient("XSRF-TOKEN=abc123; session=xyz")
    assert client.session.headers.get("X-XSRF-TOKEN") == "abc123"


def test_empty_cookie_raises():
    with pytest.raises(BattleNetAuthError, match="No Battle.net session"):
        BattleNetClient("")


@patch("clients.battlenet_client.requests.Session")
def test_get_raw_account_401(mock_session_cls):
    session = MagicMock()
    mock_session_cls.return_value = session
    resp = MagicMock()
    resp.status_code = 401
    session.get.return_value = resp
    client = BattleNetClient("session=old")
    with pytest.raises(BattleNetAuthError, match="Connections tab"):
        client.get_raw_account()
    session.get.assert_called_once_with(ACCOUNT_URL, timeout=30)


@patch("clients.battlenet_client.requests.Session")
def test_get_raw_account_success(mock_session_cls):
    session = MagicMock()
    mock_session_cls.return_value = session
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"gameAccounts": []}
    session.get.return_value = resp
    client = BattleNetClient("session=ok")
    data = client.get_raw_account()
    assert data == {"gameAccounts": []}


@patch("clients.battlenet_client.BattleNetClient.get_raw_account")
def test_probe_session_delegates(mock_get):
    mock_get.return_value = {"modernGames": []}
    assert probe_session("session=ok") == {"modernGames": []}
    mock_get.assert_called_once()


@patch("clients.battlenet_client.BattleNetClient.get_raw_account")
def test_probe_session_raises_on_auth(mock_get):
    mock_get.side_effect = BattleNetAuthError("Battle.net rejected the session (401).")
    with pytest.raises(BattleNetAuthError):
        probe_session("session=bad")
