"""Single source of truth for itch.io videogame vs non-game classification."""

from __future__ import annotations

# Matches dashboard (js/state.js) and fetcher genre noise filtering.
ITCH_NON_GAME_CLASSIFICATIONS = frozenset({
    "tool",
    "assets",
    "asset_pack",
    "comic",
    "book",
    "soundtrack",
    "physical_game",
    "other",
})


def itch_is_videogame(row: dict) -> bool:
    """True when a row should count as a library game (UI, fetch --games-only, enrichers)."""
    c = (row.get("classification") or "").strip().lower()
    if not c:
        return True
    return c not in ITCH_NON_GAME_CLASSIFICATIONS
