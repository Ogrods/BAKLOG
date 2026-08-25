"""Field overrides must only apply allowlisted keys."""

from __future__ import annotations

from fetchers.build_free_claims import FIELD_OVERRIDE_KEYS, _apply_field_overrides


def test_apply_field_overrides_ignores_unknown_keys() -> None:
    items = [
        {
            "id": "steam-demo",
            "store": "steam",
            "title": "Demo",
            "claim_url": "https://example.com/a",
            "blurb": "keep me",
            "header_image": "https://example.com/cover.jpg",
        }
    ]
    _apply_field_overrides(
        items,
        field_overrides={
            "steam-demo": {
                "title": "Renamed",
                "blurb": "should not apply",
                "header_image": "https://evil.example/x.jpg",
                "ends_at": "2099-01-01T00:00:00Z",
            }
        },
    )
    assert items[0]["title"] == "Renamed"
    assert items[0]["ends_at"] == "2099-01-01T00:00:00Z"
    assert items[0]["blurb"] == "keep me"
    assert items[0]["header_image"] == "https://example.com/cover.jpg"
    assert "blurb" not in FIELD_OVERRIDE_KEYS
