"""Compact JSON helpers for games_*.json payloads."""

from __future__ import annotations

from typing import Any

# Keys often left null by fetchers; omit on write to shrink files.
NULL_STRIP_KEYS: frozenset[str] = frozenset(
    {
        "hltb_main_hours",
        "hltb_main_extra_hours",
        "hltb_completionist_hours",
        "hltb_match_confidence",
        "hltb_name",
        "hltb_id",
        "steam_review_percent",
        "steam_review_count",
        "library_image",
        "header_image",
        "store_url",
        "release_date",
        "price_cents",
        "price_discount_percent",
    }
)


def slim_row(row: dict[str, Any], *, extra_null_keys: frozenset[str] | None = None) -> dict[str, Any]:
    """Drop keys whose value is None (and optional extra keys)."""
    skip = NULL_STRIP_KEYS | (extra_null_keys or frozenset())
    return {k: v for k, v in row.items() if v is not None or k not in skip}


def slim_games_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Slim every game row in a standard games_*.json document."""
    games = payload.get("games")
    if not isinstance(games, list):
        return payload
    out = dict(payload)
    out["games"] = [slim_row(g) if isinstance(g, dict) else g for g in games]
    return out


def dumps_games_json(payload: dict[str, Any], *, indent: int = 2) -> str:
    """JSON text for a games file with null-stub fields removed."""
    import json

    return json.dumps(slim_games_payload(payload), indent=indent, ensure_ascii=False)
