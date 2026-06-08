"""Shared helpers for deriving normalized metadata from a Steam appdetails payload.

A Steam ``appdetails`` ``data`` blob contains a lot of useful structured data
(categories, genres, metacritic, controller support, release date, achievement
totals). This module centralizes how we project that blob into the fields the
dashboard actually consumes, so:

  - ``fetch_games.py`` and ``enrich_steam_tags.py`` agree on coop classification.
  - Non-Steam libraries can be enriched from the same Steam appid mapping that
    ``enrich_steam_reviews.py`` already maintains.

Nothing in here makes network calls; pass in an already-loaded payload.
"""

from __future__ import annotations

# Category descriptions returned by store.steampowered.com/api/appdetails.
# A bare "Co-op" (no flavor) is intentionally left out — we'd rather report
# (False, False) than guess wrong about online vs split-screen.
_ONLINE_COOP_CATEGORIES = {"online co-op", "lan co-op"}
_LOCAL_COOP_CATEGORIES = {"shared/split screen co-op"}


def coop_flags_from_categories(categories: list[dict] | None) -> tuple[bool, bool]:
    """Return (coop_online, coop_local) by scanning Steam category descriptions.

    LAN Co-op is folded into ``coop_online`` because the dashboard's
    "online co-op" filter is really "multi-machine co-op" — LAN counts.
    """
    if not categories:
        return (False, False)
    names = {str(c.get("description") or "").strip().lower() for c in categories}
    online = bool(names & _ONLINE_COOP_CATEGORIES)
    local = bool(names & _LOCAL_COOP_CATEGORIES)
    return (online, local)


def _string_list(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        text = str(item).strip() if item is not None else ""
        if text:
            out.append(text)
    return out


def early_access_from_appdetails(details: dict | None) -> bool:
    """True when Steam marks the title as Early Access or coming soon."""
    if not details:
        return False
    release = details.get("release_date") or {}
    if release.get("coming_soon") is True:
        return True
    for g in details.get("genres") or []:
        if not isinstance(g, dict):
            continue
        desc = str(g.get("description") or "").strip().lower()
        if "early access" in desc:
            return True
    return False


def enrichment_from_appdetails(details: dict | None) -> dict:
    """Project a Steam ``appdetails`` ``data`` payload into a normalized dict.

    All fields are returned, even when None / empty / False, so callers can use
    a single shape regardless of how much Steam knows about the title.

    Returned keys:
      coop_online           bool
      coop_local            bool
      genres                list[str]
      release_date          str | None
      metacritic_score      int | None
      developers            list[str]
      publishers            list[str]
      controller_support    str | None
      early_access          bool
    """
    empty = {
        "coop_online": False,
        "coop_local": False,
        "genres": [],
        "release_date": None,
        "metacritic_score": None,
        "developers": [],
        "publishers": [],
        "controller_support": None,
        "early_access": False,
    }
    if not details:
        return empty

    coop_online, coop_local = coop_flags_from_categories(details.get("categories"))

    genres_raw = details.get("genres") or []
    genres: list[str] = []
    for g in genres_raw:
        if not isinstance(g, dict):
            continue
        desc = g.get("description")
        if not desc:
            continue
        desc_str = str(desc).strip()
        if desc_str:
            genres.append(desc_str)

    release_date = (details.get("release_date") or {}).get("date") or None
    if isinstance(release_date, str):
        release_date = release_date.strip() or None

    metacritic = details.get("metacritic") or {}
    score = metacritic.get("score") if isinstance(metacritic, dict) else None
    if score is not None:
        try:
            score = int(score)
        except (TypeError, ValueError):
            score = None

    controller = details.get("controller_support")
    if controller is not None:
        controller = str(controller).strip() or None

    return {
        "coop_online": coop_online,
        "coop_local": coop_local,
        "genres": genres,
        "release_date": release_date,
        "metacritic_score": score,
        "developers": _string_list(details.get("developers")),
        "publishers": _string_list(details.get("publishers")),
        "controller_support": controller,
        "early_access": early_access_from_appdetails(details),
    }


# Per-store rule set for what enrich_steam_tags is allowed to write.
#
# Steam owns coop_online / coop_local for non-Steam rows — no other fetcher
# produces them. Genres and release_date can come from the store APIs, so we
# only fill those when the row is missing the value.
ALWAYS_WRITE_FIELDS: frozenset[str] = frozenset({
    "coop_online",
    "coop_local",
})

# Fields where we only write when the row is missing the value. Stores that
# already populate these win.
FILL_IF_MISSING_FIELDS: frozenset[str] = frozenset({
    "genres",
    "release_date",
    "metacritic_score",
    "developers",
    "publishers",
    "controller_support",
    "early_access",
})


def _is_empty(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) == 0
    return False


def apply_enrichment_to_row(row: dict, enrichment: dict) -> dict:
    """Merge a normalized enrichment dict onto a library row.

    Mutates and returns ``row``. Empty/None values from ``enrichment`` never
    overwrite an existing populated field, even for ALWAYS_WRITE fields —
    a missing Steam value shouldn't clobber good data.
    """
    for key in ALWAYS_WRITE_FIELDS:
        if key not in enrichment:
            continue
        new_val = enrichment[key]
        # Don't clobber a populated field with None/empty.
        if _is_empty(new_val) and not _is_empty(row.get(key)):
            continue
        row[key] = new_val

    for key in FILL_IF_MISSING_FIELDS:
        if key not in enrichment:
            continue
        if not _is_empty(row.get(key)):
            continue
        new_val = enrichment[key]
        if _is_empty(new_val):
            continue
        row[key] = new_val

    return row
