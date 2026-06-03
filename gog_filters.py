"""Shared GOG library filters (local Galaxy DB and web fetch).

Name-based rules align the local Galaxy slice and web ``_build_game_row`` path
with games-only semantics: drop vouchers/DLC-by-title, collapse Prime/Luna/
Prime Giveaway promo dupes, drop bundle SKUs when every component is already
owned, and drop metadata-barren duplicate SKUs when a populated twin exists.
"""

from __future__ import annotations

import re
from typing import Any

_PROMO_SUFFIX_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\s*-\s*Amazon Luna\s*$", re.IGNORECASE),
    re.compile(r"\s*-\s*Amazon Prime\s*$", re.IGNORECASE),
    re.compile(r"\s*-\s*Prime Giveaway\s*$", re.IGNORECASE),
)

_DLC_NAME_RE = re.compile(r"\bDLC\b", re.IGNORECASE)
_YEAR_QUALIFIER_RE = re.compile(r"\s*\(\d{4}\)\s*$")

_NON_GAME_TITLES = frozenset({"freedom to buy games"})

_PACK_REGISTRY: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    (
        re.compile(r"^Silver Box Classics$", re.IGNORECASE),
        (
            "Heroes of the Lance",
            "Dragons of Flame",
            "War of the Lance",
            "Shadow Sorcerer",
        ),
    ),
    (
        re.compile(
            r"^Forgotten Realms: The Archives - Collection One$", re.IGNORECASE
        ),
        (
            "Eye of the Beholder",
            "Eye of the Beholder II: The Legend of Darkmoon",
            "Eye of the Beholder III: Assault on Myth Drannor",
        ),
    ),
    (
        re.compile(
            r"^Forgotten Realms: The Archives - Collection Two$", re.IGNORECASE
        ),
        (
            "Pool of Radiance",
            "Curse of the Azure Bonds",
            "Hillsfar",
            "Secret of the Silver Blades",
            "Pools of Darkness",
            "Gateway to the Savage Frontier",
            "Treasures of the Savage Frontier",
        ),
    ),
    (
        re.compile(
            r"^Forgotten Realms: The Archives - Collection Three$", re.IGNORECASE
        ),
        (
            "Dungeon Hack",
            "Menzoberranzan",
        ),
    ),
)


def is_non_game_title(name: str) -> bool:
    return (name or "").strip().lower() in _NON_GAME_TITLES


def looks_like_dlc_name(name: str) -> bool:
    return bool(_DLC_NAME_RE.search(name or ""))


def should_skip_gog_title(name: str) -> bool:
    """Drop a row before it enters the catalog (voucher / name-DLC)."""
    return is_non_game_title(name) or looks_like_dlc_name(name)


def has_promo_suffix(name: str) -> bool:
    return any(pat.search(name or "") for pat in _PROMO_SUFFIX_RES)


def canonical_gog_title(name: str) -> str:
    out = name or ""
    for pat in _PROMO_SUFFIX_RES:
        out = pat.sub("", out)
    return out.strip()


def norm_gog_title(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def dedupe_key(name: str) -> str:
    """Canonical grouping key: promo suffix stripped, trailing (YYYY) removed."""
    base = _YEAR_QUALIFIER_RE.sub("", canonical_gog_title(name))
    return norm_gog_title(base)


def _row_name(row: dict[str, Any]) -> str:
    return str(row.get("name") or "")


def row_is_metadata_barren(row: dict[str, Any]) -> bool:
    """True when Galaxy/web row has no cover image and no genres."""
    return not (row.get("header_image") or "").strip() and not row.get("genres")


def collapse_promo_suffix_dupes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop promo-branded GOG SKUs that duplicate a clean title; rename the rest."""
    clean_norms: set[str] = set()
    for row in rows:
        name = _row_name(row)
        if not has_promo_suffix(name):
            clean_norms.add(norm_gog_title(name))

    out: list[dict[str, Any]] = []
    kept_promo_norms: set[str] = set()
    for row in rows:
        name = _row_name(row)
        if not has_promo_suffix(name):
            out.append(row)
            continue
        canonical = canonical_gog_title(name)
        norm = norm_gog_title(canonical)
        if norm in clean_norms or norm in kept_promo_norms:
            continue
        out.append({**row, "name": canonical})
        kept_promo_norms.add(norm)
    return out


def collapse_pack_dupes(
    rows: list[dict[str, Any]],
    *,
    pack_component_keys: dict[str, set[str]] | None = None,
    owned_release_keys: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Drop collection/bundle SKUs when every component is already owned."""
    norms_present = {norm_gog_title(_row_name(r)) for r in rows}
    out: list[dict[str, Any]] = []
    for row in rows:
        canonical = canonical_gog_title(_row_name(row))
        drop = False

        rk = row.get("release_key")
        if (
            rk
            and pack_component_keys
            and owned_release_keys
            and rk in pack_component_keys
        ):
            components = pack_component_keys[rk]
            if components and components.issubset(owned_release_keys):
                drop = True

        if not drop:
            for pack_pat, components in _PACK_REGISTRY:
                if not pack_pat.match(canonical):
                    continue
                if all(norm_gog_title(c) in norms_present for c in components):
                    drop = True
                break

        if not drop:
            out.append(row)
    return out


def collapse_metadata_barren_dupes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop metadata-barren SKUs when a populated same-canonical twin exists."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(dedupe_key(_row_name(row)), []).append(row)

    out: list[dict[str, Any]] = []
    for row in rows:
        grp = groups[dedupe_key(_row_name(row))]
        if (
            len(grp) > 1
            and row_is_metadata_barren(row)
            and any(not row_is_metadata_barren(other) for other in grp)
        ):
            continue
        out.append(row)
    return out


def apply_gog_name_filters(rows: list[dict[str, Any]], **pack_kw: Any) -> list[dict[str, Any]]:
    """Promo + pack + metadata-barren collapse on rows that have a ``name`` field."""
    rows = collapse_promo_suffix_dupes(rows)
    rows = collapse_pack_dupes(rows, **pack_kw)
    return collapse_metadata_barren_dupes(rows)


def filter_gog_game_rows(games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Post-merge pass: promo/pack collapse on catalog rows (may mix gog_id sources)."""
    return apply_gog_name_filters(games)
