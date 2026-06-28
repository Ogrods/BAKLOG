"""Xbox CDN image URL normalization in fetch_xbox."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("fetchers.fetch_xbox", _ROOT / "fetchers/fetch_xbox.py")
_mod = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_mod)

_https = _mod._https


def test_https_upgrades_http() -> None:
    assert _https("http://example.com/x") == "https://example.com/x"


def test_https_rewrites_xbox_eds_host() -> None:
    bad = "https://images-eds.xboxlive.com/image?url=abc"
    good = "https://images-eds-ssl.xboxlive.com/image?url=abc"
    assert _https(bad) == good


def test_https_leaves_microsoft_store_urls() -> None:
    url = "https://store-images.s-microsoft.com/image/apps.12345"
    assert _https(url) == url


def test_https_none_and_empty() -> None:
    assert _https(None) is None
    assert _https("") is None
