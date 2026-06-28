from __future__ import annotations
from unittest.mock import patch
from auth.manager import PRESERVE_PROFILE_ON_RECONNECT, _should_clear_on_reconnect

def test_epic_wishlist_preserves_profile_on_reconnect() -> None:
    assert _should_clear_on_reconnect('epic_wishlist') is False

def test_gog_clears_profile_on_reconnect() -> None:
    assert _should_clear_on_reconnect('gog') is True

def test_epic_wishlist_in_preserve_set() -> None:
    assert 'epic_wishlist' in PRESERVE_PROFILE_ON_RECONNECT

def test_epic_wishlist_clears_profile_when_disconnected() -> None:
    from auth.manager import start_browser_auth
    with patch('auth.manager._provider_state', return_value='disconnected'), patch('auth.manager.clear_browser_session') as clear_mock, patch('auth.manager.threading.Thread'):
        start_browser_auth('epic_wishlist', fresh=False)
    clear_mock.assert_called_once_with('epic_wishlist')