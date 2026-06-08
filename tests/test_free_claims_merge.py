"""Tests for auto-sourced free-claim discovery and merge."""

from __future__ import annotations

from datetime import UTC, datetime

from shared.free_claims_sources import (
    carry_claim_enrichment,
    claim_match_keys,
    dedup_claim_items_by_id,
    merge_manual_and_auto,
    norm_title,
    parse_epic_element,
    parse_gamerpower_item,
    parse_itad_rss,
    platforms_to_store,
    should_skip_itad_title,
)


def _epic_element(*, discount: int, title: str = "Free Game", slug: str = "free-game-123") -> dict:
    return {
        "title": title,
        "offerMappings": [{"pageSlug": slug, "pageType": "productHome"}],
        "keyImages": [{"type": "OfferImageWide", "url": "https://example.com/wide.jpg"}],
        "promotions": {
            "promotionalOffers": [
                {
                    "promotionalOffers": [
                        {
                            "startDate": "2020-01-01T00:00:00.000Z",
                            "endDate": "2099-12-31T23:59:59.000Z",
                            "discountSetting": {
                                "discountType": "PERCENTAGE",
                                "discountPercentage": discount,
                            },
                        }
                    ]
                }
            ],
            "upcomingPromotionalOffers": [],
        },
    }


def test_epic_keeps_only_zero_discount_offers():
    now = datetime(2026, 6, 7, tzinfo=UTC)
    free = parse_epic_element(_epic_element(discount=0), now=now)
    sale = parse_epic_element(_epic_element(discount=20, title="On Sale"), now=now)
    assert free is not None
    assert free["store"] == "epic"
    assert free["claim_url"].endswith("/free-game-123")
    assert sale is None


def test_gamerpower_platforms_to_store_mapping():
    assert platforms_to_store("PC, Steam") == "steam"
    assert platforms_to_store("PC, Epic Games Store") == "epic"
    assert platforms_to_store("PC, GOG, DRM-Free") == "gog"
    assert platforms_to_store("PC, Itch.io, DRM-Free") == "itch"


def test_gamerpower_parses_end_date_and_na():
    active = parse_gamerpower_item(
        {
            "id": 42,
            "title": "Test Game (Steam) Giveaway",
            "status": "Active",
            "platforms": "PC, Steam",
            "open_giveaway_url": "https://www.gamerpower.com/open/test",
            "end_date": "2026-06-08 23:59:00",
            "image": "https://example.com/img.jpg",
            "description": "Free on Steam.",
        }
    )
    no_end = parse_gamerpower_item(
        {
            "id": 43,
            "title": "No End Game (GOG) Giveaway",
            "status": "Active",
            "platforms": "PC, GOG",
            "open_giveaway_url": "https://www.gamerpower.com/open/no-end",
            "end_date": "N/A",
        }
    )
    assert active is not None
    assert active["store"] == "steam"
    assert active["ends_at"] == "2026-06-08T23:59:00Z"
    assert no_end is not None
    assert no_end["ends_at"] is None


def test_itad_filters_bundle_and_noise_titles():
    assert should_skip_itad_title("Build your own Bundle Fanatical") is True
    assert should_skip_itad_title("Free Beta Access Key") is True
    rss = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Steam Free Game Giveaway</title>
      <link>https://isthereanydeal.com/giveaway/steam-free</link>
      <description>Claim on Steam.</description>
    </item>
    <item>
      <title>Build your own Bundle</title>
      <link>https://isthereanydeal.com/giveaway/bundle</link>
      <description>Fanatical bundle.</description>
    </item>
  </channel>
</rss>"""
    items = parse_itad_rss(rss)
    assert len(items) == 1
    assert items[0]["store"] == "steam"
    assert items[0]["source"] == "itad"


def test_dedup_by_id_keeps_cross_source_same_title():
    items = dedup_claim_items_by_id(
        [
            {
                "id": "gamerpower-1",
                "store": "epic",
                "title": "Relaxing Simulator",
                "claim_url": "https://www.gamerpower.com/open/relaxing",
                "source": "gamerpower",
            },
            {
                "id": "epic-relaxing-simulator",
                "store": "epic",
                "title": "Relaxing Simulator",
                "claim_url": "https://store.epicgames.com/en-US/p/relaxing-simulator",
                "source": "epic",
            },
        ]
    )
    assert len(items) == 2
    sources = {item["source"] for item in items}
    assert sources == {"gamerpower", "epic"}


def test_dedup_by_id_collapses_same_id_prefers_epic():
    items = dedup_claim_items_by_id(
        [
            {
                "id": "epic-relaxing-simulator",
                "store": "epic",
                "title": "Relaxing Simulator (GamerPower)",
                "claim_url": "https://www.gamerpower.com/open/relaxing",
                "source": "gamerpower",
            },
            {
                "id": "epic-relaxing-simulator",
                "store": "epic",
                "title": "Relaxing Simulator",
                "claim_url": "https://store.epicgames.com/en-US/p/relaxing-simulator",
                "source": "epic",
            },
        ]
    )
    assert len(items) == 1
    assert items[0]["source"] == "epic"


def test_merge_manual_wins_on_duplicate_title_and_id():
    manual = [
        {
            "id": "epic-manual",
            "store": "epic",
            "title": "Manual Override",
            "claim_url": "https://example.com/manual",
        }
    ]
    auto = [
        {
            "id": "epic-manual",
            "store": "epic",
            "title": "Manual Override",
            "claim_url": "https://store.epicgames.com/en-US/p/auto",
            "source": "epic",
        },
        {
            "id": "gog-auto",
            "store": "gog",
            "title": "GOG Freebie",
            "claim_url": "https://www.gog.com/game/freebie",
            "source": "gamerpower",
        },
    ]
    merged = merge_manual_and_auto(manual, auto)
    assert len(merged) == 2
    assert merged[0]["claim_url"] == "https://example.com/manual"
    assert merged[1]["id"] == "gog-auto"


def test_carry_claim_enrichment_fills_missing_fields_only() -> None:
    fresh = {
        "id": "itad-b07aac9ebd26",
        "store": "epic",
        "title": "Wytchwood",
        "claim_url": "https://example.com/w",
        "header_image": None,
    }
    existing = {
        "id": "itad-b07aac9ebd26",
        "header_image": "https://cdn.example/portrait.jpg",
        "review_percent": 93,
        "steam_appid": 729000,
        "genres": ["Adventure"],
    }
    out = carry_claim_enrichment(fresh, existing)
    assert out["header_image"] == existing["header_image"]
    assert out["review_percent"] == 93
    assert out["steam_appid"] == 729000
    assert out["genres"] == ["Adventure"]
    assert out["title"] == "Wytchwood"


def test_claim_match_keys_appid_and_title() -> None:
    keys = claim_match_keys(
        {
            "id": "gamerpower-2386",
            "title": "Tell Me Why (Steam) Giveaway",
            "steam_appid": 1180660,
        }
    )
    assert keys == {"appid:1180660", "title:tell me why"}


def test_claim_match_keys_title_only() -> None:
    keys = claim_match_keys(
        {
            "id": "epic-songs-of-conquest",
            "title": "Songs of Conquest",
        }
    )
    assert keys == {"title:songs of conquest"}


def test_claim_match_keys_empty_when_no_title_or_appid() -> None:
    assert claim_match_keys({"id": "itad-x", "title": "!!!"}) == set()


def test_norm_title_treats_ampersand_and_and_as_equivalent() -> None:
    assert norm_title("Mr.Brocco & Co") == "mr brocco and co"
    assert norm_title("Mr.Brocco And Co (IndieGala) Giveaway") == "mr brocco and co"


def test_claim_match_keys_collapses_ampersand_and_and_titles() -> None:
    amp = claim_match_keys({"id": "itad-brocco", "title": "Mr.Brocco & Co"})
    and_title = claim_match_keys(
        {"id": "gp-brocco", "title": "Mr.Brocco And Co (IndieGala) Giveaway"}
    )
    assert amp & and_title == {"title:mr brocco and co"}


def test_carry_claim_enrichment_does_not_clobber_fresh_cover() -> None:
    fresh = {
        "id": "gamerpower-1",
        "header_image": "https://www.gamerpower.com/new.jpg",
    }
    existing = {"id": "gamerpower-1", "header_image": "https://cdn.example/old.jpg"}
    out = carry_claim_enrichment(fresh, existing)
    assert out["header_image"] == "https://www.gamerpower.com/new.jpg"
