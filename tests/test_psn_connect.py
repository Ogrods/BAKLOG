from __future__ import annotations
from unittest.mock import MagicMock
from auth.runner import _fetch_npsso_background

def test_ssocookie_api_used_when_cookie_jar_empty() -> None:
    page = MagicMock()
    page.evaluate.return_value = 'fresh-from-ssocookie-token-value'
    context = MagicMock()
    context.cookies.return_value = []
    token, source = _fetch_npsso_background(page, context)
    assert source == 'ssocookie'
    assert token == 'fresh-from-ssocookie-token-value'

def test_ssocookie_api_preferred_over_stale_cookie_jar() -> None:
    page = MagicMock()
    page.evaluate.return_value = 'fresh-from-ssocookie'
    context = MagicMock()
    context.cookies.return_value = [{'name': 'npsso', 'value': 'stale-jar-token'}]
    token, source = _fetch_npsso_background(page, context)
    assert source == 'ssocookie'
    assert token == 'fresh-from-ssocookie'

def test_cookie_jar_used_when_ssocookie_empty() -> None:
    page = MagicMock()
    page.evaluate.return_value = ''
    context = MagicMock()
    context.cookies.return_value = [{'name': 'npsso', 'value': 'jar-only-token'}]
    token, source = _fetch_npsso_background(page, context)
    assert source == 'cookie'
    assert token == 'jar-only-token'