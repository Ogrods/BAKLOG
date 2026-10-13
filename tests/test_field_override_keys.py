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


def test_title_fallback_does_not_match_a_substring_title() -> None:
    items = [{"id": "gamerpower-1", "store": "steam", "title": "Outrage", "claim_url": "https://a"}]
    overrides = {"gamerpower-9": {"title": "Rage", "claim_url": "https://rage", "ends_at": "2026-11-01T00:00:00Z"}}
    _apply_field_overrides(items, field_overrides=overrides)
    assert items[0] == {"id": "gamerpower-1", "store": "steam", "title": "Outrage", "claim_url": "https://a"}
    exact = [{"id": "gamerpower-2", "store": "steam", "title": "Rage", "claim_url": "https://a"}]
    _apply_field_overrides(exact, field_overrides=overrides)
    assert exact[0]["claim_url"] == "https://rage"
