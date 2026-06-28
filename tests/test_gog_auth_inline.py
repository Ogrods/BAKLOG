from __future__ import annotations
from auth.runner import INLINE_PROVIDERS, pick_gog_al_from_cookies

class TestPickGogAlFromCookies:

    def test_reads_gog_al_cookie(self) -> None:
        cookies = [{'name': 'other', 'value': 'x', 'domain': '.gog.com'}, {'name': 'gog-al', 'value': 'session-token-abc', 'domain': '.gog.com'}]
        assert pick_gog_al_from_cookies(cookies) == 'session-token-abc'

    def test_empty_when_no_session(self) -> None:
        assert pick_gog_al_from_cookies([]) == ''
        assert pick_gog_al_from_cookies([{'name': 'other', 'value': 'y'}]) == ''

    def test_parses_gog_al_from_header_without_other_cookies(self) -> None:
        cookies = [{'name': 'prefs', 'value': 'x', 'domain': '.gog.com'}, {'name': 'other', 'value': 'y=1', 'domain': '.gog.com'}]
        assert pick_gog_al_from_cookies(cookies) == ''

class TestGogInlineProvider:

    def test_gog_in_inline_providers(self) -> None:
        assert 'gog' in INLINE_PROVIDERS