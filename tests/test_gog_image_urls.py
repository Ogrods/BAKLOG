"""GOG CDN image URL builder: hash → header + vertical cover."""

from __future__ import annotations

from clients.gog_galaxy_client import _pick_cover_url
from fetchers.fetch_gog import _gog_image_urls

HASH = "11b5d020144f3ef465bc36c4d375e579fa65e2858b4f58cdd5540a049b9a6982"
BASE = f"https://images.gog.com/{HASH}"


def test_bare_hash_path_uses_landscape_jpg() -> None:
    header, library = _gog_image_urls(BASE)
    assert header == f"{BASE}.jpg"
    assert library == f"{BASE}.jpg"


def test_mangled_padding_webp_rebuilds_to_jpg() -> None:
    raw = f"{BASE}_glx_bg_top_padding_7.webp?namespace=gamesdb_glx_vertical_cover.jpg"
    header, library = _gog_image_urls(raw)
    assert header == f"{BASE}.jpg"
    assert library == f"{BASE}.jpg"


def test_protocol_relative_hash() -> None:
    header, library = _gog_image_urls(f"//{BASE.removeprefix('https://')}")
    assert header == f"{BASE}.jpg"
    assert library == f"{BASE}.jpg"


def test_pick_cover_prefers_background_before_vertical() -> None:
    url = _pick_cover_url(
        {
            "background": "https://images.gog.com/bg_padding.webp",
            "cover": "https://images.gog.com/cover_vertical.jpg",
        }
    )
    assert url == "https://images.gog.com/bg_padding.webp"


def test_pick_cover_falls_back_to_cover() -> None:
    url = _pick_cover_url({"cover": "https://images.gog.com/cover_vertical.jpg"})
    assert url == "https://images.gog.com/cover_vertical.jpg"
