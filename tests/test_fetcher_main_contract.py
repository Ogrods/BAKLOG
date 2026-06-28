from __future__ import annotations
import sys
from unittest.mock import patch
import pytest
from clients.psn_client import PsnAuthError
from clients.ubisoft_client import UbisoftAuthError
from clients.xbox_client import XboxAuthError
from fetchers._progress import EXIT_CODE_AUTH

def test_fetch_psn_main_missing_npsso_exits_1(monkeypatch: pytest.MonkeyPatch) -> None:
    import fetchers.fetch_psn as fetch_psn
    monkeypatch.setattr(fetch_psn, 'resolve_env', lambda *_a, **_k: None)
    monkeypatch.setattr(sys, 'argv', ['fetch_psn'])
    assert fetch_psn.main() == 1

def test_fetch_psn_main_auth_failure_exits_4(monkeypatch: pytest.MonkeyPatch) -> None:
    import fetchers.fetch_psn as fetch_psn
    mark_calls: list = []
    monkeypatch.setattr(fetch_psn, 'resolve_env', lambda *_a, **_k: 'npsso-token')
    monkeypatch.setattr(fetch_psn, 'mark_invalid', lambda *a, **k: mark_calls.append((a, k)))
    with patch.object(fetch_psn, 'PsnClient') as mock_client:
        mock_client.return_value.validate_session.side_effect = PsnAuthError('expired')
        monkeypatch.setattr(sys, 'argv', ['fetch_psn', '--skip-hltb'])
        assert fetch_psn.main() == EXIT_CODE_AUTH
    assert mark_calls

def test_fetch_xbox_main_missing_api_key_exits_1(monkeypatch: pytest.MonkeyPatch) -> None:
    import fetchers.fetch_xbox as fetch_xbox
    monkeypatch.setattr(fetch_xbox, 'resolve_env', lambda *_a, **_k: None)
    monkeypatch.setattr(sys, 'argv', ['fetch_xbox'])
    assert fetch_xbox.main() == 1

def test_fetch_xbox_main_auth_failure_exits_4(monkeypatch: pytest.MonkeyPatch) -> None:
    import fetchers.fetch_xbox as fetch_xbox
    mark_calls: list = []
    monkeypatch.setattr(fetch_xbox, 'resolve_env', lambda *_a, **_k: 'xbl-key')
    monkeypatch.setattr(fetch_xbox, 'mark_invalid', lambda *a, **k: mark_calls.append((a, k)))
    with patch.object(fetch_xbox, 'XboxClient') as mock_client:
        mock_client.return_value.get_gamertag.return_value = 'tester'
        mock_client.return_value.get_title_history.side_effect = XboxAuthError('expired')
        monkeypatch.setattr(sys, 'argv', ['fetch_xbox', '--skip-hltb'])
        assert fetch_xbox.main() == EXIT_CODE_AUTH
    assert mark_calls

def test_fetch_ubisoft_main_missing_creds_exits_1(monkeypatch: pytest.MonkeyPatch) -> None:
    import fetchers.fetch_ubisoft as fetch_ubisoft
    monkeypatch.setattr(fetch_ubisoft, 'resolve_env', lambda *_a, **_k: None)
    monkeypatch.setattr(sys, 'argv', ['fetch_ubisoft'])
    assert fetch_ubisoft.main() == 1

def test_fetch_ubisoft_main_auth_failure_exits_4(monkeypatch: pytest.MonkeyPatch) -> None:
    import fetchers.fetch_ubisoft as fetch_ubisoft
    mark_calls: list = []

    def _resolve(key: str, provider=None) -> str | None:
        return {'UBISOFT_AUTH': 'Ubi_v1 t=x', 'UBISOFT_SESSION_ID': 'sess'}.get(key)
    monkeypatch.setattr(fetch_ubisoft, 'resolve_env', _resolve)
    monkeypatch.setattr(fetch_ubisoft, 'mark_invalid', lambda *a, **k: mark_calls.append((a, k)))
    with patch.object(fetch_ubisoft, 'UbisoftClient') as mock_client:
        mock_client.return_value.get_library.side_effect = UbisoftAuthError('expired')
        monkeypatch.setattr(sys, 'argv', ['fetch_ubisoft', '--skip-hltb'])
        assert fetch_ubisoft.main() == EXIT_CODE_AUTH
    assert mark_calls