"""Tests for opt-in approved auto-claim filtering in build_free_claims.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import build_free_claims as bfc


def test_clean_blurb_strips_urls_and_boilerplate() -> None:
    raw = (
        '<a href="https://isthereanydeal.com/g/portal2/info/">Portal 2</a> '
        "expires on Jun 10 | go to giveaway"
    )
    assert bfc._clean_blurb(raw) == "Portal 2"
    assert bfc._clean_blurb("title https://example.com/x extra") == "title extra"


def test_load_approved_ids_missing_file(tmp_path: Path) -> None:
    assert bfc._load_approved_ids(tmp_path / "missing.json") == set()


def test_load_approved_ids_reads_ids(tmp_path: Path) -> None:
    path = tmp_path / "approved.json"
    path.write_text(json.dumps({"ids": ["epic-a", "gamerpower-1"]}), encoding="utf-8")
    assert bfc._load_approved_ids(path) == {"epic-a", "gamerpower-1"}


def test_load_approved_ids_ignores_bad_file(tmp_path: Path) -> None:
    path = tmp_path / "approved.json"
    path.write_text("{not json", encoding="utf-8")
    assert bfc._load_approved_ids(path) == set()


def test_load_premium_only_ids_reads_list(tmp_path: Path) -> None:
    path = tmp_path / "approved.json"
    path.write_text(
        json.dumps({"ids": ["a"], "premium_only_ids": ["a", "b"]}),
        encoding="utf-8",
    )
    assert bfc._load_premium_only_ids(path) == {"a", "b"}


def test_apply_premium_only_stamps_and_clears() -> None:
    items = [
        {"id": "auto-a", "store": "steam", "title": "A", "claim_url": "https://a"},
        {"id": "manual-b", "store": "epic", "title": "B", "claim_url": "https://b", "premium_only": True},
        {"id": "free-c", "store": "gog", "title": "C", "claim_url": "https://c", "premium_only": True},
    ]
    bfc._apply_premium_only(
        items,
        premium_only_ids={"auto-a"},
        manual_items=[{"id": "manual-b", "premium_only": True}],
    )
    assert items[0].get("premium_only") is True
    assert items[1].get("premium_only") is True
    assert "premium_only" not in items[2]


def test_preview_publish_items_stamps_premium_only() -> None:
    from datetime import UTC, datetime

    now = datetime(2026, 6, 8, 12, 0, 0, tzinfo=UTC)
    items = bfc.preview_publish_items(
        manual_items=[{
            "id": "manual-pro",
            "store": "steam",
            "title": "Manual Pro",
            "claim_url": "https://example.com/manual",
            "premium_only": True,
        }],
        auto_items_all=[{
            "id": "auto-pro",
            "store": "epic",
            "title": "Auto Pro",
            "claim_url": "https://example.com/auto",
        }],
        approved_ids={"auto-pro"},
        premium_only_ids={"auto-pro"},
        now=now,
    )
    by_id = {it["id"]: it for it in items}
    assert by_id["auto-pro"].get("premium_only") is True
    assert by_id["manual-pro"].get("premium_only") is True


def test_infer_store_from_text_maps_itchio_giveaways() -> None:
    assert bfc._infer_store_from_text(
        "other",
        "Flufftopia (itchio) Giveaway",
        "Flufftopia is free on itch.io until June 14th 2026.",
        "https://www.gamerpower.com/open/flufftopia-itchio-giveaway",
    ) == "itch"


def test_infer_store_from_text_maps_indiegala_giveaways() -> None:
    assert bfc._infer_store_from_text(
        "other",
        "Carlos the Taco (IndieGala) Giveaway",
        "Download Carlos the Taco for free via IndieGala.",
        "https://www.gamerpower.com/open/carlos-the-taco-pc-giveaway",
    ) == "indiegala"


def test_infer_store_from_text_prefers_itch_over_indiegala() -> None:
    assert bfc._infer_store_from_text(
        "other",
        "Some Game",
        "Free on itch.io, also listed on IndieGala.",
        "",
    ) == "itch"


def test_infer_store_from_text_keeps_explicit_store() -> None:
    assert bfc._infer_store_from_text("epic", "Foo", "", "") == "epic"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-06-11T15:00:00", "2026-06-11T15:00:00Z"),       # naive → assume UTC
        ("2026-06-08T23:59:00Z", "2026-06-08T23:59:00Z"),      # already canonical
        ("2026-06-11T15:00:00-07:00", "2026-06-11T22:00:00Z"), # offset → UTC
        ("2026-06-11T15:00:00.123456+00:00", "2026-06-11T15:00:00Z"),  # drop microseconds
        (None, None),
        ("", None),
        ("not a date", "not a date"),                          # unparseable kept as-is
    ],
)
def test_normalize_ends_at(value: object, expected: str | None) -> None:
    assert bfc._normalize_ends_at(value) == expected


def test_enrich_item_normalizes_ends_at() -> None:
    out = bfc._enrich_item(
        {
            "id": "epic-foo",
            "store": "epic",
            "title": "Foo",
            "claim_url": "https://store.epicgames.com/en-US/p/foo",
            "ends_at": "2026-06-11T15:00:00-07:00",
        },
        [0.0],
    )
    assert out["ends_at"] == "2026-06-11T22:00:00Z"


def test_resolve_ends_at_defaults_epic_from_first_seen() -> None:
    from datetime import UTC, datetime

    now = datetime(2026, 6, 11, 12, 0, 0, tzinfo=UTC)
    raw = {
        "source": "epic",
        "first_seen": "2026-06-01T00:00:00Z",
    }
    assert bfc._resolve_ends_at(raw, now=now) == "2026-06-15T00:00:00Z"


def test_resolve_ends_at_defaults_itad_without_date() -> None:
    from datetime import UTC, datetime

    now = datetime(2026, 6, 11, 12, 0, 0, tzinfo=UTC)
    raw = {
        "source": "itad",
        "first_seen": "2026-06-01T00:00:00Z",
    }
    assert bfc._resolve_ends_at(raw, now=now) == "2026-06-15T00:00:00Z"


def test_resolve_ends_at_keeps_existing_longer_date() -> None:
    raw = {
        "source": "epic",
        "ends_at": "2026-08-01T00:00:00Z",
    }
    assert bfc._resolve_ends_at(raw) == "2026-08-01T00:00:00Z"


def test_enrich_item_defaults_epic_ends_at_without_upstream_date() -> None:
    from datetime import UTC, datetime

    now = datetime(2026, 6, 11, 12, 0, 0, tzinfo=UTC)
    out = bfc._enrich_item(
        {
            "id": "epic-bar",
            "store": "epic",
            "title": "Bar",
            "claim_url": "https://store.epicgames.com/en-US/p/bar",
            "source": "epic",
            "first_seen": "2026-06-01T00:00:00Z",
        },
        [0.0],
        now=now,
    )
    assert out["ends_at"] == "2026-06-15T00:00:00Z"


def test_build_publishes_only_approved_auto_items(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "free-claims.input.json"
    auto_path = tmp_path / "free_claims.auto.json"
    approved_path = tmp_path / "free_claims.approved.json"
    output_path = tmp_path / "free-claims.json"

    input_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "manual-1",
                        "store": "steam",
                        "title": "Manual Always",
                        "claim_url": "https://store.steampowered.com/app/1",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    auto_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "epic-approved",
                        "store": "epic",
                        "title": "Approved Epic",
                        "claim_url": "https://store.epicgames.com/en-US/p/approved",
                        "source": "epic",
                    },
                    {
                        "id": "gog-hidden",
                        "store": "gog",
                        "title": "Hidden GOG",
                        "claim_url": "https://www.gog.com/game/hidden",
                        "source": "gamerpower",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    approved_path.write_text(json.dumps({"ids": ["epic-approved"]}), encoding="utf-8")

    monkeypatch.setattr(bfc, "INPUT_PATH", input_path)
    monkeypatch.setattr(bfc, "AUTO_PATH", auto_path)
    monkeypatch.setattr(bfc, "APPROVED_PATH", approved_path)
    monkeypatch.setattr(bfc, "OUTPUT_PATH", output_path)
    monkeypatch.setattr(bfc, "FALLBACK_PATH", tmp_path / "fallback.json")
    monkeypatch.setattr(bfc, "free_claims_path", lambda: tmp_path / "profile.json")
    monkeypatch.setattr(
        bfc,
        "_enrich_item",
        lambda raw, last_call, cover_lookup=None, **kwargs: {
            "id": raw["id"],
            "store": raw["store"],
            "title": raw["title"],
            "claim_url": raw["claim_url"],
        },
    )
    monkeypatch.setattr(sys, "argv", ["build_free_claims.py", "--no-profile"])

    assert bfc.main() == 0
    built = json.loads(output_path.read_text(encoding="utf-8"))
    ids = {item["id"] for item in built["items"]}
    assert ids == {"manual-1", "epic-approved"}


def test_build_without_approved_file_publishes_manual_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "free-claims.input.json"
    auto_path = tmp_path / "free_claims.auto.json"
    approved_path = tmp_path / "free_claims.approved.json"
    output_path = tmp_path / "free-claims.json"

    input_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "manual-only",
                        "store": "steam",
                        "title": "Manual Only",
                        "claim_url": "https://store.steampowered.com/app/2",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    auto_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "epic-unapproved",
                        "store": "epic",
                        "title": "Should Not Publish",
                        "claim_url": "https://store.epicgames.com/en-US/p/nope",
                        "source": "epic",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(bfc, "INPUT_PATH", input_path)
    monkeypatch.setattr(bfc, "AUTO_PATH", auto_path)
    monkeypatch.setattr(bfc, "APPROVED_PATH", approved_path)
    monkeypatch.setattr(bfc, "OUTPUT_PATH", output_path)
    monkeypatch.setattr(bfc, "FALLBACK_PATH", tmp_path / "fallback.json")
    monkeypatch.setattr(bfc, "free_claims_path", lambda: tmp_path / "profile.json")
    monkeypatch.setattr(
        bfc,
        "_enrich_item",
        lambda raw, last_call, cover_lookup=None, **kwargs: {
            "id": raw["id"],
            "store": raw["store"],
            "title": raw["title"],
            "claim_url": raw["claim_url"],
        },
    )
    monkeypatch.setattr(sys, "argv", ["build_free_claims.py", "--no-profile"])

    assert bfc.main() == 0
    built = json.loads(output_path.read_text(encoding="utf-8"))
    assert [item["id"] for item in built["items"]] == ["manual-only"]


def test_build_skips_manual_row_when_approved_false(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "free-claims.input.json"
    auto_path = tmp_path / "free_claims.auto.json"
    approved_path = tmp_path / "free_claims.approved.json"
    output_path = tmp_path / "free-claims.json"

    input_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "manual-on",
                        "store": "steam",
                        "title": "Manual On",
                        "claim_url": "https://store.steampowered.com/app/1",
                    },
                    {
                        "id": "manual-off",
                        "store": "steam",
                        "title": "Manual Off",
                        "claim_url": "https://store.steampowered.com/app/2",
                        "approved": False,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    auto_path.write_text(json.dumps({"items": []}), encoding="utf-8")

    monkeypatch.setattr(bfc, "INPUT_PATH", input_path)
    monkeypatch.setattr(bfc, "AUTO_PATH", auto_path)
    monkeypatch.setattr(bfc, "APPROVED_PATH", approved_path)
    monkeypatch.setattr(bfc, "OUTPUT_PATH", output_path)
    monkeypatch.setattr(bfc, "FALLBACK_PATH", tmp_path / "fallback.json")
    monkeypatch.setattr(bfc, "free_claims_path", lambda: tmp_path / "profile.json")
    monkeypatch.setattr(
        bfc,
        "_enrich_item",
        lambda raw, last_call, cover_lookup=None, **kwargs: {
            "id": raw["id"],
            "store": raw["store"],
            "title": raw["title"],
            "claim_url": raw["claim_url"],
        },
    )
    monkeypatch.setattr(sys, "argv", ["build_free_claims.py", "--no-profile", "--allow-empty"])

    assert bfc.main() == 0
    built = json.loads(output_path.read_text(encoding="utf-8"))
    assert [item["id"] for item in built["items"]] == ["manual-on"]


def test_build_require_manual_approval_needs_explicit_true(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "free-claims.input.json"
    auto_path = tmp_path / "free_claims.auto.json"
    approved_path = tmp_path / "free_claims.approved.json"
    output_path = tmp_path / "free-claims.json"

    input_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "manual-implicit",
                        "store": "steam",
                        "title": "Implicit",
                        "claim_url": "https://store.steampowered.com/app/1",
                    },
                    {
                        "id": "manual-explicit",
                        "store": "steam",
                        "title": "Explicit",
                        "claim_url": "https://store.steampowered.com/app/2",
                        "approved": True,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    auto_path.write_text(json.dumps({"items": []}), encoding="utf-8")

    monkeypatch.setattr(bfc, "INPUT_PATH", input_path)
    monkeypatch.setattr(bfc, "AUTO_PATH", auto_path)
    monkeypatch.setattr(bfc, "APPROVED_PATH", approved_path)
    monkeypatch.setattr(bfc, "OUTPUT_PATH", output_path)
    monkeypatch.setattr(bfc, "FALLBACK_PATH", tmp_path / "fallback.json")
    monkeypatch.setattr(bfc, "free_claims_path", lambda: tmp_path / "profile.json")
    monkeypatch.setattr(
        bfc,
        "_enrich_item",
        lambda raw, last_call, cover_lookup=None, **kwargs: {
            "id": raw["id"],
            "store": raw["store"],
            "title": raw["title"],
            "claim_url": raw["claim_url"],
        },
    )
    monkeypatch.setattr(sys, "argv", ["build_free_claims.py", "--no-profile", "--allow-empty", "--require-manual-approval"])

    assert bfc.main() == 0
    built = json.loads(output_path.read_text(encoding="utf-8"))
    assert [item["id"] for item in built["items"]] == ["manual-explicit"]


def test_build_applies_field_overrides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "free-claims.input.json"
    auto_path = tmp_path / "free_claims.auto.json"
    approved_path = tmp_path / "free_claims.approved.json"
    output_path = tmp_path / "free-claims.json"

    input_path.write_text(json.dumps({"items": []}), encoding="utf-8")
    auto_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "epic-approved",
                        "store": "epic",
                        "title": "Original Title",
                        "claim_url": "https://store.epicgames.com/en-US/p/original",
                        "ends_at": "2099-01-01T00:00:00Z",
                        "source": "epic",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    approved_path.write_text(
        json.dumps(
            {
                "ids": ["epic-approved"],
                "field_overrides": {
                    "epic-approved": {
                        "title": "Edited Title",
                        "claim_url": "https://store.epicgames.com/en-US/p/edited",
                        "ends_at": "2099-06-01T12:00:00Z",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(bfc, "INPUT_PATH", input_path)
    monkeypatch.setattr(bfc, "AUTO_PATH", auto_path)
    monkeypatch.setattr(bfc, "APPROVED_PATH", approved_path)
    monkeypatch.setattr(bfc, "OUTPUT_PATH", output_path)
    monkeypatch.setattr(bfc, "FALLBACK_PATH", tmp_path / "fallback.json")
    monkeypatch.setattr(bfc, "free_claims_path", lambda: tmp_path / "profile.json")
    monkeypatch.setattr(
        bfc,
        "_enrich_item",
        lambda raw, last_call, cover_lookup=None, **kwargs: {
            "id": raw["id"],
            "store": raw["store"],
            "title": raw["title"],
            "claim_url": raw["claim_url"],
            "ends_at": raw.get("ends_at"),
        },
    )
    monkeypatch.setattr(sys, "argv", ["build_free_claims.py", "--no-profile"])

    assert bfc.main() == 0
    built = json.loads(output_path.read_text(encoding="utf-8"))
    assert len(built["items"]) == 1
    item = built["items"][0]
    assert item["title"] == "Edited Title"
    assert item["claim_url"] == "https://store.epicgames.com/en-US/p/edited"
    assert item["ends_at"] == "2099-06-01T12:00:00Z"


def test_field_override_extends_ends_at_before_expiry_prune(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "free-claims.input.json"
    auto_path = tmp_path / "free_claims.auto.json"
    approved_path = tmp_path / "free_claims.approved.json"
    output_path = tmp_path / "free-claims.json"

    input_path.write_text(json.dumps({"items": []}), encoding="utf-8")
    auto_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "epic-old",
                        "store": "epic",
                        "title": "Extended Game",
                        "claim_url": "https://store.epicgames.com/en-US/p/old",
                        "ends_at": "2020-01-01T00:00:00Z",
                        "source": "epic",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    approved_path.write_text(
        json.dumps(
            {
                "ids": ["epic-old"],
                "field_overrides": {
                    "epic-old": {"ends_at": "2099-06-01T12:00:00Z"},
                },
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(bfc, "INPUT_PATH", input_path)
    monkeypatch.setattr(bfc, "AUTO_PATH", auto_path)
    monkeypatch.setattr(bfc, "APPROVED_PATH", approved_path)
    monkeypatch.setattr(bfc, "OUTPUT_PATH", output_path)
    monkeypatch.setattr(bfc, "FALLBACK_PATH", tmp_path / "fallback.json")
    monkeypatch.setattr(bfc, "free_claims_path", lambda: tmp_path / "profile.json")
    monkeypatch.setattr(
        bfc,
        "_enrich_item",
        lambda raw, last_call, cover_lookup=None, **kwargs: {
            "id": raw["id"],
            "store": raw["store"],
            "title": raw["title"],
            "claim_url": raw["claim_url"],
            "ends_at": raw.get("ends_at"),
        },
    )
    monkeypatch.setattr(sys, "argv", ["build_free_claims.py", "--no-profile"])

    assert bfc.main() == 0
    built = json.loads(output_path.read_text(encoding="utf-8"))
    assert {item["id"] for item in built["items"]} == {"epic-old"}
    approved = json.loads(approved_path.read_text(encoding="utf-8"))
    assert approved["ids"] == ["epic-old"]


def test_rekey_approved_state_migrates_stale_id_to_current_feed_id() -> None:
    auto_items = [
        {
            "id": "gamerpower-new",
            "store": "steam",
            "title": "Tell Me Why",
            "claim_url": "https://x",
            "steam_appid": 1180660,
            "source": "gamerpower",
        }
    ]
    ids, store, fields, premium = bfc.rekey_approved_state(
        ids=["itad-old"],
        store_overrides={"itad-old": "steam"},
        field_overrides={"itad-old": {"title": "Tell Me Why"}},
        premium_only_ids={"itad-old"},
        auto_items_all=auto_items,
        prior_rows_by_id={},
    )
    assert ids == ["gamerpower-new"]
    assert store["gamerpower-new"] == "steam"
    assert fields["gamerpower-new"]["title"] == "Tell Me Why"
    assert premium == {"gamerpower-new"}


def test_build_prunes_expired_approved_and_manual_items(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "free-claims.input.json"
    auto_path = tmp_path / "free_claims.auto.json"
    approved_path = tmp_path / "free_claims.approved.json"
    output_path = tmp_path / "free-claims.json"

    input_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "manual-expired",
                        "store": "steam",
                        "title": "Expired Manual",
                        "claim_url": "https://store.steampowered.com/app/999",
                        "ends_at": "2020-01-01T00:00:00Z",
                    },
                    {
                        "id": "manual-live",
                        "store": "steam",
                        "title": "Live Manual",
                        "claim_url": "https://store.steampowered.com/app/1000",
                        "ends_at": "2099-01-01T00:00:00Z",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    auto_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "epic-expired",
                        "store": "epic",
                        "title": "Expired Epic",
                        "claim_url": "https://store.epicgames.com/en-US/p/expired",
                        "ends_at": "2020-01-01T00:00:00Z",
                        "source": "epic",
                    },
                    {
                        "id": "epic-live",
                        "store": "epic",
                        "title": "Live Epic",
                        "claim_url": "https://store.epicgames.com/en-US/p/live",
                        "ends_at": "2099-01-01T00:00:00Z",
                        "source": "epic",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    approved_path.write_text(
        json.dumps(
            {
                "ids": ["epic-expired", "epic-live"],
                "store_overrides": {"epic-expired": "steam"},
                "field_overrides": {"epic-expired": {"title": "Should Be Pruned"}},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(bfc, "INPUT_PATH", input_path)
    monkeypatch.setattr(bfc, "AUTO_PATH", auto_path)
    monkeypatch.setattr(bfc, "APPROVED_PATH", approved_path)
    monkeypatch.setattr(bfc, "OUTPUT_PATH", output_path)
    monkeypatch.setattr(bfc, "FALLBACK_PATH", tmp_path / "fallback.json")
    monkeypatch.setattr(bfc, "free_claims_path", lambda: tmp_path / "profile.json")
    monkeypatch.setattr(
        bfc,
        "_enrich_item",
        lambda raw, last_call, cover_lookup=None, **kwargs: {
            "id": raw["id"],
            "store": raw["store"],
            "title": raw["title"],
            "claim_url": raw["claim_url"],
            "ends_at": raw.get("ends_at"),
        },
    )
    monkeypatch.setattr(sys, "argv", ["build_free_claims.py", "--no-profile"])

    assert bfc.main() == 0
    built = json.loads(output_path.read_text(encoding="utf-8"))
    ids = {item["id"] for item in built["items"]}
    assert ids == {"manual-live", "epic-live"}

    approved = json.loads(approved_path.read_text(encoding="utf-8"))
    assert approved["ids"] == ["epic-live"]
    assert "epic-expired" not in (approved.get("store_overrides") or {})
    assert "epic-expired" not in (approved.get("field_overrides") or {})


def test_enrich_item_resolves_steam_appid_and_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    last_call = [0.0]
    raw = {
        "id": "gamerpower-999",
        "store": "steam",
        "title": "Portal 2 (Steam) Giveaway",
        "claim_url": "https://www.gamerpower.com/open/portal-2",
        "source": "gamerpower",
    }

    monkeypatch.setattr(
        bfc,
        "_steam_storesearch",
        lambda term, lc: [{"id": 620, "name": "Portal 2"}],
    )
    monkeypatch.setattr(
        bfc,
        "_steam_app_details",
        lambda appid, lc: {
            "name": "Portal 2",
            "header_image": "https://cdn.example/portal2.jpg",
            "genres": [{"description": "Action"}],
        },
    )
    monkeypatch.setattr(bfc, "_steam_review_percent", lambda appid, lc: 98)
    monkeypatch.setattr(
        bfc,
        "_verified_portrait_cover",
        lambda appid, lc: bfc._steam_portrait_cover(appid),
    )

    out = bfc._enrich_item(raw, last_call)

    assert out["id"] == "gamerpower-999"
    assert out["steam_appid"] == 620
    assert out["review_percent"] == 98
    assert out["header_image"] == bfc._steam_portrait_cover(620)
    assert out["genres"] == ["Action"]


def test_enrich_item_keeps_dash_when_no_appid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    last_call = [0.0]
    raw = {
        "id": "gamerpower-888",
        "store": "steam",
        "title": "Unknown Obscure Title (Steam) Giveaway",
        "claim_url": "https://www.gamerpower.com/open/obscure",
    }

    monkeypatch.setattr(bfc, "_steam_storesearch", lambda term, lc: [])
    monkeypatch.setattr(bfc, "_resolve_steam_appid", lambda **kwargs: None)

    out = bfc._enrich_item(raw, last_call)

    assert out["id"] == "gamerpower-888"
    assert "steam_appid" not in out
    assert "review_percent" not in out


def test_enrich_item_resolves_steam_cover_for_non_steam_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = {
        "id": "itad-b07aac9ebd26",
        "store": "epic",
        "title": "Wytchwood free for mobile on EGS on Epic Game Store",
        "claim_url": "https://isthereanydeal.com/giveaways/16242/",
        "header_image": None,
        "source": "itad",
    }
    monkeypatch.setattr(
        bfc,
        "_steam_storesearch",
        lambda term, lc: [{"id": 1016800, "name": "Wytchwood"}],
    )
    monkeypatch.setattr(
        bfc,
        "_steam_app_details",
        lambda appid, lc: {
            "name": "Wytchwood",
            "header_image": "https://cdn.example/wytchwood.jpg",
            "genres": [{"description": "Adventure"}],
        },
    )
    monkeypatch.setattr(bfc, "_steam_review_percent", lambda appid, lc: 91)
    monkeypatch.setattr(
        bfc,
        "_verified_portrait_cover",
        lambda appid, lc: bfc._steam_portrait_cover(appid),
    )

    out = bfc._enrich_item(raw, [0.0])

    assert out["store"] == "epic"
    assert out["steam_appid"] == 1016800
    assert out["header_image"] == bfc._steam_portrait_cover(1016800)
    assert out["review_percent"] == 91
    assert out["genres"] == []


def test_enrich_item_upgrades_gamerpower_cover_to_portrait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = {
        "id": "gamerpower-2386",
        "store": "steam",
        "title": "Tell Me Why (Steam) Giveaway",
        "claim_url": "https://www.gamerpower.com/open/tell-me-why-steam-giveaway",
        "header_image": "https://www.gamerpower.com/offers/1b/6478b9dcae7be.jpg",
        "source": "gamerpower",
    }
    monkeypatch.setattr(
        bfc,
        "_steam_storesearch",
        lambda term, lc: [{"id": 1180660, "name": "Tell Me Why"}],
    )
    monkeypatch.setattr(
        bfc,
        "_steam_app_details",
        lambda appid, lc: {"name": "Tell Me Why", "genres": []},
    )
    monkeypatch.setattr(bfc, "_steam_review_percent", lambda appid, lc: 82)
    monkeypatch.setattr(
        bfc,
        "_verified_portrait_cover",
        lambda appid, lc: bfc._steam_portrait_cover(appid),
    )

    out = bfc._enrich_item(raw, [0.0])

    assert out["steam_appid"] == 1180660
    assert out["header_image"] == bfc._steam_portrait_cover(1180660)
    assert "gamerpower.com" not in (out["header_image"] or "")


def test_enrich_item_falls_back_to_appdetails_header_when_portrait_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_header = (
        "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/"
        "973000/header.jpg"
    )
    raw = {
        "id": "itad-1b0433806065",
        "store": "indiegala",
        "title": "Die Young: Prologue",
        "claim_url": "https://isthereanydeal.com/giveaways/7433/",
        "steam_appid": 973000,
        "source": "itad",
    }
    monkeypatch.setattr(bfc, "_verified_portrait_cover", lambda appid, lc: None)
    monkeypatch.setattr(
        bfc,
        "_steam_app_details",
        lambda appid, lc: {
            "name": "Die Young: Prologue",
            "header_image": real_header,
        },
    )
    monkeypatch.setattr(bfc, "_steam_review_percent", lambda appid, lc: 78)

    out = bfc._enrich_item(raw, [0.0])

    assert out["steam_appid"] == 973000
    assert out["header_image"] == real_header
    assert out["header_image"] != bfc._steam_portrait_cover(973000)


def test_enrich_item_uses_verified_portrait_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = {
        "id": "gamerpower-2386",
        "store": "steam",
        "title": "Tell Me Why (Steam) Giveaway",
        "claim_url": "https://www.gamerpower.com/open/tell-me-why-steam-giveaway",
        "steam_appid": 1180660,
        "source": "gamerpower",
    }
    monkeypatch.setattr(
        bfc,
        "_verified_portrait_cover",
        lambda appid, lc: bfc._steam_portrait_cover(appid),
    )
    monkeypatch.setattr(
        bfc,
        "_steam_app_details",
        lambda appid, lc: {
            "name": "Tell Me Why",
            "header_image": "https://cdn.example/tell-me-why-header.jpg",
        },
    )
    monkeypatch.setattr(bfc, "_steam_review_percent", lambda appid, lc: 82)

    out = bfc._enrich_item(raw, [0.0])

    assert out["header_image"] == bfc._steam_portrait_cover(1180660)


def test_enrich_item_skips_network_when_fully_enriched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    portrait = bfc._steam_portrait_cover(620)
    raw = {
        "id": "steam-620",
        "store": "steam",
        "title": "Portal 2",
        "claim_url": "https://store.steampowered.com/app/620",
        "steam_appid": 620,
        "header_image": portrait,
        "review_percent": 98,
        "genres": ["Action", "Adventure"],
    }
    details_calls: list[int] = []
    portrait_calls: list[int] = []
    review_calls: list[int] = []

    monkeypatch.setattr(
        bfc,
        "_steam_app_details",
        lambda appid, lc: details_calls.append(appid) or None,
    )
    monkeypatch.setattr(
        bfc,
        "_verified_portrait_cover",
        lambda appid, lc: portrait_calls.append(appid) or portrait,
    )
    monkeypatch.setattr(
        bfc,
        "_steam_review_percent",
        lambda appid, lc: review_calls.append(appid) or 98,
    )

    out = bfc._enrich_item(raw, [0.0])

    assert out["steam_appid"] == 620
    assert out["review_percent"] == 98
    assert out["header_image"] == portrait
    assert out["genres"] == ["Action", "Adventure"]
    assert details_calls == []
    assert portrait_calls == []
    assert review_calls == []


def test_enrich_item_publish_skips_portrait_upgrade_for_reviewed_gp_thumb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = {
        "id": "gamerpower-3684",
        "store": "steam",
        "title": "Eets (Steam) Giveaway",
        "claim_url": "https://www.gamerpower.com/open/eets-steam-giveaway",
        "steam_appid": 6100,
        "header_image": "https://www.gamerpower.com/offers/1b/6a2aebf9e069c.jpg",
        "review_percent": 59,
        "genres": ["Casual", "Indie", "Strategy"],
    }
    portrait_calls: list[int] = []

    monkeypatch.setattr(
        bfc,
        "_verified_portrait_cover",
        lambda appid, lc: portrait_calls.append(appid) or bfc._steam_portrait_cover(appid),
    )

    out = bfc._enrich_item(raw, [0.0], upgrade_covers=False)

    assert out["review_percent"] == 59
    assert out["header_image"] == raw["header_image"]
    assert portrait_calls == []


def test_enrich_item_upgrade_covers_still_verifies_portrait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = {
        "id": "gamerpower-3684",
        "store": "steam",
        "title": "Eets (Steam) Giveaway",
        "claim_url": "https://www.gamerpower.com/open/eets-steam-giveaway",
        "steam_appid": 6100,
        "header_image": "https://www.gamerpower.com/offers/1b/6a2aebf9e069c.jpg",
        "review_percent": 59,
        "genres": ["Casual", "Indie", "Strategy"],
    }
    portrait = bfc._steam_portrait_cover(6100)
    portrait_calls: list[int] = []

    monkeypatch.setattr(
        bfc,
        "_verified_portrait_cover",
        lambda appid, lc: portrait_calls.append(appid) or portrait,
    )

    out = bfc._enrich_item(raw, [0.0], upgrade_covers=True)

    assert portrait_calls == [6100]
    assert out["header_image"] == portrait


def test_enrich_item_fetches_review_when_portrait_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    portrait = bfc._steam_portrait_cover(620)
    raw = {
        "id": "steam-620",
        "store": "steam",
        "title": "Portal 2",
        "claim_url": "https://store.steampowered.com/app/620",
        "steam_appid": 620,
        "header_image": portrait,
        "genres": ["Action"],
    }
    details_calls: list[int] = []
    portrait_calls: list[int] = []

    monkeypatch.setattr(
        bfc,
        "_steam_app_details",
        lambda appid, lc: details_calls.append(appid)
        or {
            "name": "Portal 2",
            "header_image": "https://cdn.example/portal2.jpg",
            "genres": [{"description": "Action"}],
        },
    )
    monkeypatch.setattr(bfc, "_steam_review_percent", lambda appid, lc: 95)
    monkeypatch.setattr(
        bfc,
        "_verified_portrait_cover",
        lambda appid, lc: portrait_calls.append(appid) or portrait,
    )

    out = bfc._enrich_item(raw, [0.0])

    assert out["review_percent"] == 95
    assert details_calls == [620]
    assert portrait_calls == []


def test_enrich_item_borrows_cover_from_sibling_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        bfc,
        "_resolve_steam_appid_by_title",
        lambda title, lc, blurb=None: None,
    )
    lookup = bfc._build_cover_lookup(
        [
            {
                "id": "gamerpower-3096",
                "title": "Madness Inside (itch.io) Giveaway",
                "header_image": "https://www.gamerpower.com/offers/madness.jpg",
            }
        ]
    )
    raw = {
        "id": "itad-d85d5bb4128d",
        "store": "itch",
        "title": "Madness Inside free on itchio on Itch.io",
        "claim_url": "https://isthereanydeal.com/giveaways/15895/",
        "header_image": None,
        "source": "itad",
    }
    out = bfc._enrich_item(raw, [0.0], lookup)
    assert out["header_image"] == "https://www.gamerpower.com/offers/madness.jpg"


def test_enrich_item_upgrades_cover_when_sibling_has_better_portrait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    steam_portrait = bfc._steam_portrait_cover(2074560)
    gamerpower_banner = "https://www.gamerpower.com/offers/1b/68ce9db7d6736.jpg"
    monkeypatch.setattr(
        bfc,
        "_resolve_steam_appid_by_title",
        lambda title, lc, blurb=None: None,
    )
    lookup = bfc._build_cover_lookup(
        [
            {
                "id": "itad-brocco",
                "title": "Mr.Brocco & Co - FREE on IndieGala on IndieGala Store",
                "header_image": steam_portrait,
            }
        ]
    )
    raw = {
        "id": "gamerpower-3287",
        "store": "other",
        "title": "Mr.Brocco And Co (IndieGala) Giveaway",
        "claim_url": "https://www.gamerpower.com/open/mr-brocco-and-co-pc-giveaway",
        "header_image": gamerpower_banner,
        "source": "gamerpower",
    }
    out = bfc._enrich_item(raw, [0.0], lookup)
    assert out["header_image"] == steam_portrait


def test_resolve_steam_appid_from_itad_blurb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bfc, "_steam_storesearch", lambda term, lc: [])
    appid = bfc._resolve_steam_appid(
        store="steam",
        title="Gravity Circuit free on Steam on Steam",
        claim_url="https://isthereanydeal.com/giveaways/16228/",
        blurb='go to <a href="https://store.steampowered.com/app/858710/Gravity_Circuit/">giveaway</a>',
        last_call=[0.0],
    )
    assert appid == 858710


def test_preview_publish_items_carries_live_review_percent() -> None:
    from datetime import UTC, datetime

    now = datetime(2026, 6, 8, 12, 0, 0, tzinfo=UTC)
    items = bfc.preview_publish_items(
        manual_items=[],
        auto_items_all=[
            {
                "id": "epic-rogue-waters-9764d6",
                "store": "epic",
                "title": "Rogue Waters",
                "claim_url": "https://store.epicgames.com/en-US/p/rogue-waters",
                "ends_at": "2026-12-01T00:00:00Z",
            },
        ],
        approved_ids={"epic-rogue-waters-9764d6"},
        live_items=[
            {
                "id": "epic-rogue-waters-9764d6",
                "store": "epic",
                "title": "Rogue Waters",
                "claim_url": "https://store.epicgames.com/en-US/p/rogue-waters",
                "review_percent": 76,
            },
        ],
        now=now,
    )
    assert len(items) == 1
    assert items[0]["review_percent"] == 76


def test_preview_publish_items_borrows_review_by_title_when_id_differs() -> None:
    """A re-keyed ITAD copy (no appid, different id than the live Epic row) should
    still borrow the review % from its same-title live sibling."""
    from datetime import UTC, datetime

    now = datetime(2026, 6, 8, 12, 0, 0, tzinfo=UTC)
    items = bfc.preview_publish_items(
        manual_items=[],
        auto_items_all=[
            {
                "id": "itad-0c69ed1f1bd8",
                "store": "epic",
                "title": "Rogue Waters",
                "claim_url": "https://store.epicgames.com/en-US/p/rogue-waters",
                "ends_at": "2026-12-01T00:00:00Z",
            },
        ],
        approved_ids={"itad-0c69ed1f1bd8"},
        live_items=[
            {
                "id": "epic-rogue-waters-9764d6",
                "store": "epic",
                "title": "Rogue Waters",
                "claim_url": "https://store.epicgames.com/en-US/p/rogue-waters",
                "review_percent": 76,
            },
        ],
        now=now,
    )
    assert len(items) == 1
    assert items[0]["id"] == "itad-0c69ed1f1bd8"
    assert items[0]["review_percent"] == 76


def test_preview_publish_items_carries_forward_approved_missing_from_feed() -> None:
    """An approved claim absent from the fresh auto feed but still present in the
    live feed (not dismissed, not expired) must be carried into the preview, just
    like the build does, so it is not falsely reported as removed."""
    from datetime import UTC, datetime

    now = datetime(2026, 6, 8, 12, 0, 0, tzinfo=UTC)
    items = bfc.preview_publish_items(
        manual_items=[],
        auto_items_all=[],
        approved_ids={"itad-9dcfdf2b0b35"},
        live_items=[
            {
                "id": "itad-9dcfdf2b0b35",
                "store": "itad",
                "title": "Remothered: Tormented Fathers",
                "claim_url": "https://example.com/remothered",
                "review_percent": 74,
                "ends_at": None,
            },
        ],
        now=now,
    )
    assert [it["id"] for it in items] == ["itad-9dcfdf2b0b35"]


def test_preview_publish_items_does_not_carry_dismissed_or_expired() -> None:
    from datetime import UTC, datetime

    now = datetime(2026, 6, 8, 12, 0, 0, tzinfo=UTC)
    items = bfc.preview_publish_items(
        manual_items=[],
        auto_items_all=[],
        approved_ids={"itad-dismissed", "itad-expired"},
        dismissed_ids={"itad-dismissed"},
        live_items=[
            {
                "id": "itad-dismissed",
                "store": "itad",
                "title": "Dismissed Game",
                "claim_url": "https://example.com/d",
            },
            {
                "id": "itad-expired",
                "store": "itad",
                "title": "Expired Game",
                "claim_url": "https://example.com/e",
                "ends_at": "2026-05-01T00:00:00Z",
            },
        ],
        now=now,
    )
    assert items == []


def test_preview_publish_items_merges_without_network() -> None:
    from datetime import UTC, datetime

    now = datetime(2026, 6, 8, 12, 0, 0, tzinfo=UTC)
    items = bfc.preview_publish_items(
        manual_items=[
            {
                "id": "manual-1",
                "store": "steam",
                "title": "Manual",
                "claim_url": "https://store.steampowered.com/app/1",
            }
        ],
        auto_items_all=[
            {
                "id": "epic-ok",
                "store": "epic",
                "title": "Epic Game",
                "claim_url": "https://store.epicgames.com/en-US/p/ok",
                "ends_at": "2026-12-01T00:00:00Z",
            },
            {
                "id": "epic-old",
                "store": "epic",
                "title": "Expired",
                "claim_url": "https://store.epicgames.com/en-US/p/old",
                "ends_at": "2026-05-01T00:00:00Z",
            },
        ],
        approved_ids={"epic-ok"},
        now=now,
    )
    ids = {it["id"] for it in items}
    assert ids == {"manual-1", "epic-ok"}
    assert all(it.get("claim_url") and it.get("store") for it in items)


def test_itad_slug_from_blurb() -> None:
    blurb = '<a href="https://isthereanydeal.com/game/wytchwood/info/">Wytchwood</a>'
    assert bfc._itad_slug_from_blurb(blurb) == "wytchwood"


def test_resolve_steam_appid_by_title_uses_itad_slug_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_search(term: str, lc: list[float]) -> list[dict]:
        calls.append(term)
        if term == "wytchwood":
            return [{"id": 729000, "name": "Wytchwood"}]
        return []

    monkeypatch.setattr(bfc, "_steam_storesearch", fake_search)
    appid = bfc._resolve_steam_appid_by_title(
        "Obscure Giveaway Title",
        [0.0],
        blurb='<a href="https://isthereanydeal.com/game/wytchwood/info/">Wytchwood</a>',
    )
    assert appid == 729000
    assert calls == ["Obscure Giveaway Title", "wytchwood"]


def test_build_publishes_key_matched_row_when_approved_id_flipped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Approved itad id absent after dedup; surviving epic row should still publish."""
    input_path = tmp_path / "free-claims.input.json"
    auto_path = tmp_path / "free_claims.auto.json"
    approved_path = tmp_path / "free_claims.approved.json"
    output_path = tmp_path / "free-claims.json"

    input_path.write_text(json.dumps({"items": []}), encoding="utf-8")
    auto_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "epic-songs-of-conquest",
                        "store": "epic",
                        "title": "Songs of Conquest",
                        "claim_url": "https://store.epicgames.com/en-US/p/songs-of-conquest",
                        "ends_at": "2099-01-01T00:00:00Z",
                        "source": "epic",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    approved_path.write_text(
        json.dumps(
            {
                "ids": ["itad-073a56345192"],
                "field_overrides": {
                    "itad-073a56345192": {"title": "Songs of Conquest"},
                },
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(bfc, "INPUT_PATH", input_path)
    monkeypatch.setattr(bfc, "AUTO_PATH", auto_path)
    monkeypatch.setattr(bfc, "APPROVED_PATH", approved_path)
    monkeypatch.setattr(bfc, "OUTPUT_PATH", output_path)
    monkeypatch.setattr(bfc, "FALLBACK_PATH", tmp_path / "fallback.json")
    monkeypatch.setattr(bfc, "free_claims_path", lambda: tmp_path / "profile.json")
    monkeypatch.setattr(
        bfc,
        "_enrich_item",
        lambda raw, last_call, cover_lookup=None, **kwargs: {
            "id": raw["id"],
            "store": raw["store"],
            "title": raw["title"],
            "claim_url": raw["claim_url"],
        },
    )
    monkeypatch.setattr(sys, "argv", ["build_free_claims.py", "--no-profile"])

    assert bfc.main() == 0
    built = json.loads(output_path.read_text(encoding="utf-8"))
    ids = {item["id"] for item in built["items"]}
    assert ids == {"epic-songs-of-conquest"}


def test_build_key_matched_row_inherits_store_and_field_overrides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "free-claims.input.json"
    auto_path = tmp_path / "free_claims.auto.json"
    approved_path = tmp_path / "free_claims.approved.json"
    output_path = tmp_path / "free-claims.json"

    input_path.write_text(json.dumps({"items": []}), encoding="utf-8")
    auto_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "gamerpower-3272",
                        "store": "other",
                        "title": "The Brave Little Cloud (IndieGala) Giveaway",
                        "claim_url": "https://www.gamerpower.com/open/the-brave-little-cloud-pc-giveaway",
                        "ends_at": "2099-01-01T00:00:00Z",
                        "source": "gamerpower",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    approved_path.write_text(
        json.dumps(
            {
                "ids": ["itad-dd5b5b16e035"],
                "store_overrides": {"itad-dd5b5b16e035": "indiegala"},
                "field_overrides": {
                    "itad-dd5b5b16e035": {"title": "The Brave Little Cloud"},
                },
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(bfc, "INPUT_PATH", input_path)
    monkeypatch.setattr(bfc, "AUTO_PATH", auto_path)
    monkeypatch.setattr(bfc, "APPROVED_PATH", approved_path)
    monkeypatch.setattr(bfc, "OUTPUT_PATH", output_path)
    monkeypatch.setattr(bfc, "FALLBACK_PATH", tmp_path / "fallback.json")
    monkeypatch.setattr(bfc, "free_claims_path", lambda: tmp_path / "profile.json")
    monkeypatch.setattr(
        bfc,
        "_enrich_item",
        lambda raw, last_call, cover_lookup=None, **kwargs: {
            "id": raw["id"],
            "store": raw["store"],
            "title": raw["title"],
            "claim_url": raw["claim_url"],
        },
    )
    monkeypatch.setattr(sys, "argv", ["build_free_claims.py", "--no-profile"])

    assert bfc.main() == 0
    built = json.loads(output_path.read_text(encoding="utf-8"))
    assert len(built["items"]) == 1
    item = built["items"][0]
    assert item["id"] == "gamerpower-3272"
    assert item["store"] == "indiegala"
    assert item["title"] == "The Brave Little Cloud"


def test_build_absent_approved_id_without_override_title_stays_id_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "free-claims.input.json"
    auto_path = tmp_path / "free_claims.auto.json"
    approved_path = tmp_path / "free_claims.approved.json"
    output_path = tmp_path / "free-claims.json"

    input_path.write_text(json.dumps({"items": []}), encoding="utf-8")
    auto_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "epic-other",
                        "store": "epic",
                        "title": "Unrelated Game",
                        "claim_url": "https://store.epicgames.com/en-US/p/other",
                        "ends_at": "2099-01-01T00:00:00Z",
                        "source": "epic",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    approved_path.write_text(json.dumps({"ids": ["itad-missing-no-title"]}), encoding="utf-8")

    monkeypatch.setattr(bfc, "INPUT_PATH", input_path)
    monkeypatch.setattr(bfc, "AUTO_PATH", auto_path)
    monkeypatch.setattr(bfc, "APPROVED_PATH", approved_path)
    monkeypatch.setattr(bfc, "OUTPUT_PATH", output_path)
    monkeypatch.setattr(bfc, "FALLBACK_PATH", tmp_path / "fallback.json")
    monkeypatch.setattr(bfc, "free_claims_path", lambda: tmp_path / "profile.json")
    monkeypatch.setattr(
        bfc,
        "_enrich_item",
        lambda raw, last_call, cover_lookup=None, **kwargs: {
            "id": raw["id"],
            "store": raw["store"],
            "title": raw["title"],
            "claim_url": raw["claim_url"],
        },
    )
    monkeypatch.setattr(sys, "argv", ["build_free_claims.py", "--no-profile", "--allow-empty"])

    assert bfc.main() == 0
    built = json.loads(output_path.read_text(encoding="utf-8"))
    assert built["items"] == []


def test_preview_publish_items_matches_by_stable_key() -> None:
    from datetime import UTC, datetime

    now = datetime(2026, 6, 8, 12, 0, 0, tzinfo=UTC)
    items = bfc.preview_publish_items(
        manual_items=[],
        auto_items_all=[
            {
                "id": "epic-rogue-waters-9764d6",
                "store": "epic",
                "title": "Rogue Waters",
                "claim_url": "https://store.epicgames.com/en-US/p/rogue-waters-9764d6",
                "ends_at": "2099-01-01T00:00:00Z",
            }
        ],
        approved_ids={"itad-0c69ed1f1bd8"},
        field_overrides={"itad-0c69ed1f1bd8": {"title": "Rogue Waters"}},
        now=now,
    )
    assert [item["id"] for item in items] == ["epic-rogue-waters-9764d6"]


def test_preview_publish_items_excludes_dismissed_key_matched_duplicate() -> None:
    """Hidden feed row must not re-enter via stale approved id title key."""
    from datetime import UTC, datetime

    now = datetime(2026, 6, 8, 12, 0, 0, tzinfo=UTC)
    items = bfc.preview_publish_items(
        manual_items=[],
        auto_items_all=[
            {
                "id": "epic-rogue-waters-9764d6",
                "store": "epic",
                "title": "Rogue Waters",
                "claim_url": "https://store.epicgames.com/en-US/p/rogue-waters-9764d6",
                "ends_at": "2099-01-01T00:00:00Z",
            }
        ],
        approved_ids={"itad-0c69ed1f1bd8"},
        field_overrides={"itad-0c69ed1f1bd8": {"title": "Rogue Waters"}},
        dismissed_ids={"epic-rogue-waters-9764d6"},
        now=now,
    )
    assert items == []


def test_build_excludes_dismissed_key_matched_duplicate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """main() must honor dismissed so hidden dupes do not publish."""
    input_path = tmp_path / "free-claims.input.json"
    auto_path = tmp_path / "free_claims.auto.json"
    approved_path = tmp_path / "free_claims.approved.json"
    output_path = tmp_path / "free-claims.json"

    input_path.write_text(json.dumps({"items": []}), encoding="utf-8")
    auto_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "epic-songs-of-conquest",
                        "store": "epic",
                        "title": "Songs of Conquest",
                        "claim_url": "https://store.epicgames.com/en-US/p/songs-of-conquest",
                        "ends_at": "2099-01-01T00:00:00Z",
                        "source": "epic",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    approved_path.write_text(
        json.dumps(
            {
                "ids": ["itad-073a56345192"],
                "field_overrides": {
                    "itad-073a56345192": {"title": "Songs of Conquest"},
                },
                "dismissed": ["epic-songs-of-conquest"],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(bfc, "INPUT_PATH", input_path)
    monkeypatch.setattr(bfc, "AUTO_PATH", auto_path)
    monkeypatch.setattr(bfc, "APPROVED_PATH", approved_path)
    monkeypatch.setattr(bfc, "OUTPUT_PATH", output_path)
    monkeypatch.setattr(bfc, "FALLBACK_PATH", tmp_path / "fallback.json")
    monkeypatch.setattr(bfc, "free_claims_path", lambda: tmp_path / "profile.json")
    monkeypatch.setattr(
        bfc,
        "_enrich_item",
        lambda raw, last_call, cover_lookup=None, **kwargs: {
            "id": raw["id"],
            "store": raw["store"],
            "title": raw["title"],
            "claim_url": raw["claim_url"],
        },
    )
    monkeypatch.setattr(sys, "argv", ["build_free_claims.py", "--no-profile", "--allow-empty"])

    assert bfc.main() == 0
    built = json.loads(output_path.read_text(encoding="utf-8"))
    assert built["items"] == []


def test_merge_enriched_items_into_auto_feed(tmp_path: Path) -> None:
    auto_path = tmp_path / "free_claims.auto.json"
    auto_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "itad-b07aac9ebd26",
                        "store": "epic",
                        "title": "Wytchwood",
                        "claim_url": "https://example.com/w",
                        "header_image": None,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    enriched = [
        {
            "id": "itad-b07aac9ebd26",
            "header_image": bfc._steam_portrait_cover(729000),
            "steam_appid": 729000,
            "review_percent": 93,
            "genres": ["Adventure"],
        }
    ]
    updated = bfc.merge_enriched_items_into_auto_feed(auto_path, enriched)
    assert updated == 1
    saved = json.loads(auto_path.read_text(encoding="utf-8"))
    row = saved["items"][0]
    assert row["header_image"] == bfc._steam_portrait_cover(729000)
    assert row["steam_appid"] == 729000
    assert row["review_percent"] == 93
    assert row["genres"] == ["Adventure"]


def test_merge_enriched_items_into_input_feed(tmp_path: Path) -> None:
    input_path = tmp_path / "free-claims.input.json"
    input_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "manual-1",
                        "store": "steam",
                        "title": "Manual Game",
                        "claim_url": "https://store.steampowered.com/app/1",
                        "header_image": None,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    enriched = [
        {
            "id": "manual-1",
            "header_image": bfc._steam_portrait_cover(729000),
            "steam_appid": 729000,
            "review_percent": 91,
        }
    ]
    updated = bfc.merge_enriched_items_into_input_feed(input_path, enriched)
    assert updated == 1
    saved = json.loads(input_path.read_text(encoding="utf-8"))
    row = saved["items"][0]
    assert row["header_image"] == bfc._steam_portrait_cover(729000)
    assert row["steam_appid"] == 729000
    assert row["review_percent"] == 91


def test_enrich_item_light_keeps_existing_header() -> None:
    real_header = (
        "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/"
        "973000/header.jpg"
    )
    raw = {
        "id": "itad-1b0433806065",
        "store": "indiegala",
        "title": "Die Young: Prologue",
        "claim_url": "https://isthereanydeal.com/giveaways/7433/",
        "header_image": real_header,
        "steam_appid": 973000,
        "source": "itad",
    }
    out = bfc._enrich_item_light(raw, None)
    assert out["header_image"] == real_header
    assert out["header_image"] != bfc._steam_portrait_cover(973000)


def test_enrich_item_light_synthesizes_portrait_when_no_header() -> None:
    raw = {
        "id": "gamerpower-2386",
        "store": "steam",
        "title": "Tell Me Why (Steam) Giveaway",
        "claim_url": "https://www.gamerpower.com/open/tell-me-why",
        "steam_appid": 1180660,
        "source": "gamerpower",
    }
    out = bfc._enrich_item_light(raw, None)
    assert out["header_image"] == bfc._steam_portrait_cover(1180660)


def test_enrich_item_light_borrows_live_header_image() -> None:
    raw = {
        "id": "gp-1",
        "store": "steam",
        "title": "Tell Me Why",
        "claim_url": "https://www.gamerpower.com/open/tell-me-why",
        "header_image": "https://www.gamerpower.com/offers/thumb.jpg",
        "steam_appid": 1180660,
        "source": "gamerpower",
    }
    live = {
        "id": "gp-1",
        "header_image": bfc._steam_portrait_cover(1180660),
        "review_percent": 88,
    }
    out = bfc._enrich_item_light(raw, None, live)
    assert out["header_image"] == bfc._steam_portrait_cover(1180660)
    assert out["review_percent"] == 88


def test_merge_enriched_items_overwrites_dead_portrait_with_header(
    tmp_path: Path,
) -> None:
    dead_portrait = bfc._steam_portrait_cover(973000)
    real_header = (
        "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/"
        "973000/header.jpg"
    )
    auto_path = tmp_path / "free_claims.auto.json"
    auto_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "itad-1b0433806065",
                        "store": "indiegala",
                        "title": "Die Young: Prologue",
                        "claim_url": "https://example.com/dy",
                        "header_image": dead_portrait,
                        "steam_appid": 973000,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    enriched = [
        {
            "id": "itad-1b0433806065",
            "header_image": real_header,
            "steam_appid": 973000,
            "review_percent": 78,
        }
    ]
    updated = bfc.merge_enriched_items_into_auto_feed(auto_path, enriched)
    assert updated == 1
    saved = json.loads(auto_path.read_text(encoding="utf-8"))
    assert saved["items"][0]["header_image"] == real_header


# --- Blocked tier (permanent kill list) -----------------------------------


def test_load_blocked_ids_reads_list(tmp_path: Path) -> None:
    path = tmp_path / "approved.json"
    path.write_text(
        json.dumps({"ids": ["a"], "blocked": ["x", "y", " "]}),
        encoding="utf-8",
    )
    assert bfc._load_blocked_ids(path) == {"x", "y"}


def test_load_blocked_ids_missing_file(tmp_path: Path) -> None:
    assert bfc._load_blocked_ids(tmp_path / "missing.json") == set()


def test_parse_approved_put_payload_separates_blocked() -> None:
    parsed = bfc.parse_approved_put_payload({
        "ids": ["keep-1"],
        "dismissed": ["soft-1", "shared", "keep-1"],
        "blocked": ["block-1", "shared", "keep-1"],
    })
    # Blocked wins over dismissed for a shared id; approved ids shadow both.
    assert parsed["blocked"] == ["block-1", "shared"]
    assert parsed["dismissed"] == ["soft-1"]


def test_prepare_approved_document_prunes_orphan_dismissed_keeps_blocked() -> None:
    auto_items = [
        {"id": "live-soft", "store": "steam", "title": "Live", "claim_url": "https://a"},
    ]
    out = bfc.prepare_approved_document(
        ids=[],
        store_overrides={},
        field_overrides={},
        premium_only_ids=set(),
        dismissed=["live-soft", "orphan-soft"],
        blocked=["orphan-block"],
        auto_items=auto_items,
    )
    # Dismissed id no longer in the feed is cycled out; blocked id is kept verbatim.
    assert out["dismissed"] == ["live-soft"]
    assert out["blocked"] == ["orphan-block"]


def test_main_build_excludes_blocked_from_feed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    approved = tmp_path / "approved.json"
    approved.write_text(
        json.dumps({
            "ids": ["auto-keep", "auto-block"],
            "blocked": ["auto-block"],
        }),
        encoding="utf-8",
    )
    assert bfc._load_blocked_ids(approved) == {"auto-block"}
    # Folding blocked into the dismissed filter must exclude blocked ids.
    dismissed = bfc._load_dismissed_ids(approved) | bfc._load_blocked_ids(approved)
    assert "auto-block" in dismissed


def test_build_refuses_empty_publish_without_allow_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "free-claims.input.json"
    auto_path = tmp_path / "free_claims.auto.json"
    approved_path = tmp_path / "free_claims.approved.json"
    output_path = tmp_path / "free-claims.json"
    fallback_path = tmp_path / "free_claims.fallback.json"

    output_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-06-01T00:00:00Z",
                "items": [{"id": "keep-me", "store": "epic", "title": "Old", "claim_url": "https://example.com/old"}],
            }
        ),
        encoding="utf-8",
    )
    input_path.write_text(json.dumps({"items": []}), encoding="utf-8")
    auto_path.write_text(json.dumps({"items": []}), encoding="utf-8")
    approved_path.write_text(json.dumps({"ids": []}), encoding="utf-8")

    monkeypatch.setattr(bfc, "AUTO_PATH", auto_path)
    monkeypatch.setattr(bfc, "APPROVED_PATH", approved_path)
    monkeypatch.setattr(bfc, "OUTPUT_PATH", output_path)
    monkeypatch.setattr(bfc, "FALLBACK_PATH", fallback_path)
    monkeypatch.setattr(bfc, "free_claims_path", lambda: tmp_path / "profile.json")

    import sys

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_free_claims.py",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--no-profile",
        ],
    )
    code = bfc.main()
    assert code == 2
    kept = json.loads(output_path.read_text(encoding="utf-8"))
    assert kept["items"][0]["id"] == "keep-me"
