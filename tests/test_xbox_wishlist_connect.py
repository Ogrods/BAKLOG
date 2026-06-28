from __future__ import annotations
from auth import runner as auth_runner
from auth.runner import _xbox_url_is_login, _xbox_url_on_wishlist

def test_xbox_url_on_wishlist_ignores_oauth_redirect_uri() -> None:
    oauth = 'https://login.live.com/oauth20_authorize.srf?client_id=abc&redirect_uri=https%3A%2F%2Fwww.xbox.com%2Fen-us%2Fwishlist'
    assert _xbox_url_on_wishlist(oauth) is False
    assert _xbox_url_is_login(oauth) is True

def test_xbox_url_on_wishlist_matches_real_wishlist_path() -> None:
    assert _xbox_url_on_wishlist('https://www.xbox.com/en-us/wishlist') is True
    assert _xbox_url_on_wishlist('https://www.xbox.com/en-US/wishlist') is True
    assert _xbox_url_is_login('https://www.xbox.com/en-us/wishlist') is False

def test_xbox_has_msa_session_detects_wlssc_and_xb_tokens() -> None:

    class _Ctx:

        @staticmethod
        def cookies():
            return [{'name': 'MUID', 'domain': '.live.com'}]
    assert auth_runner._xbox_has_msa_session(_Ctx()) is False

    class _Ctx2:

        @staticmethod
        def cookies():
            return [{'name': 'WLSSC', 'domain': '.live.com'}, {'name': 'XBXXtkhttp%3A%2F%2Fxboxlive.com%2F', 'domain': '.xbox.com'}]
    assert auth_runner._xbox_has_msa_session(_Ctx2()) is True