"""Global library noise rules — mirrors js/library-noise.js."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

_TRADEMARK_RE = re.compile(r"[™®©]")

# Normalized lowercase exact titles (streaming apps, store vouchers, etc.).
NOISE_EXACT_TITLES = frozenset(
    {
        "live",
        "fab listing live",
        "hbo max",
        "hbo go",
        "shadow costume for sonic",
        "sonic holiday costume",
        "lego sonic skin",
        "amazon prime video",
        "disney plus",
        "disney",
        "spotify",
        "youtube",
        "twitch",
        "netflix",
        "hulu",
        "watchesn",
        "watchespn",
        "pluto tv",
        "sharefactory",
        "share factory studio",
        "the playroom",
        "project catch",
        "directv nfl sunday ticket",
        "freedom to buy games",
    }
)

# Conservative title patterns — avoid bare \\bdlc\\b, \\bskin\\b, \\bbeta\\b.
NOISE_TITLE_RE = re.compile(
    r"(?i)("
    r"tech beta|"
    r"(?:pre[- ]?game )?editor|"
    r"resource archiver|"
    r"costume for|"
    r"public testing|"
    r"test branch|"
    r"puzzle pack|"
    r"glove skin|"
    r"soundtrack|"
    r"wallpaper$|"
    r"art book|"
    r"artbook|"
    r"digital art book|"
    r"mini digital sound|"
    r"character pack|"
    r"challenge pack|"
    r"picaro|"
    r"skin pack|"
    r"costume pack|"
    r"expansion pass|"
    r"season pass|"
    r"fighter pass|"
    r"add-?on content|"
    r"bonus content|"
    r"upgrade pack|"
    r"coin set|"
    r"nintendo switch online|"
    r"e?shop card|"
    r"add-on content bundle|"
    r"\bcontent$|"
    r"pokémon home|pokemon home|"
    r"pokémon tv|pokemon tv|"
    r"crunchyroll|"
    r"inkypen"
    r")"
)

_BETA_END_RE = re.compile(r"\s+beta\s*$", re.I)

# Nintendo fetch-time extras — stricter than global rules (eShop subs/vouchers).
_NINTENDO_EXTRA_TITLE_RE = re.compile(
    r"(?i)\b(dlc|skin|coins?|membership|expansion pack)\b"
)

# PSN-only patterns (demo/beta/themes/trophies) — not promoted globally.
_PSN_EXTRA_TITLE_RE = re.compile(
    r"(?i)("
    r"\bdemo\b|"
    r"\bopen beta\b|"
    r"\bbeta\b|"
    r"\bb e t a\b|"
    r"\btrial version\b|"
    r"\bdigital deluxe soundtrack\b|"
    r"^dlc\b|"
    r"\btrophy set$|"
    r"\btrophies$|"
    r"\btheme$|"
    r"\bdynamic theme$|"
    r"\bavatar pack\b"
    r")"
)

_GOG_DLC_RE = re.compile(r"\bDLC\b", re.I)

_PSN_ENTITLEMENT_ID_RE = re.compile(
    r"(?i)^(?:up\d+-)?(?:cusa|ppsa|npwr)\d+_\d+$"
)

_EDITION_SUFFIXES = (
    " digital deluxe edition",
    " deluxe edition",
    " gold edition",
    " ultimate edition",
    " complete edition",
    " definitive edition",
    " special edition",
    " collectors edition",
    " collector's edition",
)

_EDITION_VARIANT_SUBTITLE_RE = re.compile(
    r"\b(edition|deluxe|upgrade|complete|musical|trilogy|collection|pack|bundle|"
    r"goty|definitive|remastered|remaster|ultimate)\b",
    re.I,
)


def normalize_noise_title(name: str) -> str:
    text = _TRADEMARK_RE.sub("", name or "")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split()).strip()


def is_entitlement_slug(name: str | None) -> bool:
    """Epic internal slug titles (single token, underscore, no spaces)."""
    s = str(name or "").strip()
    return bool(s) and "_" in s and not any(ch.isspace() for ch in s)


def is_psn_entitlement_id(name: str | None) -> bool:
    return bool(_PSN_ENTITLEMENT_ID_RE.fullmatch(str(name or "").strip()))


def should_auto_hide_by_title(name: str | None) -> bool:
    raw = str(name or "").strip()
    if not raw:
        return True
    norm = normalize_noise_title(raw)
    if not norm:
        return True
    if norm in NOISE_EXACT_TITLES:
        return True
    if is_entitlement_slug(raw) or is_psn_entitlement_id(raw):
        return True
    if NOISE_TITLE_RE.search(raw) or NOISE_TITLE_RE.search(norm):
        return True
    if _BETA_END_RE.search(raw):
        return True
    return False


def should_auto_hide_nintendo_title(name: str | None) -> bool:
    raw = str(name or "").strip()
    if should_auto_hide_by_title(raw):
        return True
    return bool(_NINTENDO_EXTRA_TITLE_RE.search(raw))


def should_auto_hide_psn_title(name: str | None) -> bool:
    raw = str(name or "").strip()
    if not raw:
        return True
    if should_auto_hide_by_title(raw):
        return True
    norm = normalize_noise_title(raw)
    return bool(_PSN_EXTRA_TITLE_RE.search(raw) or _PSN_EXTRA_TITLE_RE.search(norm))


def should_auto_hide_gog_title(name: str | None) -> bool:
    raw = str(name or "").strip()
    if should_auto_hide_by_title(raw):
        return True
    return bool(_GOG_DLC_RE.search(raw))


def edition_base_key(name: str) -> str:
    """Edition-aware grouping key for within-store dedupe (not noise hide)."""
    key = normalize_noise_title(name)
    for suffix in _EDITION_SUFFIXES:
        if key.endswith(suffix):
            key = key[: -len(suffix)].strip()
    raw = str(name or "")
    if ":" in raw:
        sub = raw.split(":", 1)[1].strip()
        if sub and _EDITION_VARIANT_SUBTITLE_RE.search(sub):
            return normalize_noise_title(raw.split(":", 1)[0])
    return key


def edition_title_join_key(name: str) -> str:
    """Strip trailing edition suffixes only — for receipt↔catalog title joins."""
    key = normalize_noise_title(name)
    for suffix in _EDITION_SUFFIXES:
        if key.endswith(suffix):
            key = key[: -len(suffix)].strip()
    return key


def is_nintendo_noise_row(item: dict[str, Any]) -> bool:
    """Nintendo guardrail: pure DLC / addon entitlements + global title noise."""
    if item.get("is_dlc") or item.get("nintendo_is_dlc"):
        return True
    tags = item.get("tags") or []
    if "dlc" in tags:
        has_app = bool(
            item.get("has_application")
            or item.get("has_nx_application")
            or item.get("has_ounce_application")
            or item.get("application_id")
            or item.get("nintendo_has_application")
            or item.get("nintendo_has_nx_application")
            or item.get("nintendo_has_ounce_application")
        )
        if not has_app:
            return True
    return should_auto_hide_nintendo_title(str(item.get("name") or ""))


def is_catalog_noise_row(row: dict[str, Any]) -> bool:
    return "noise" in (row.get("tags") or [])


def is_library_noise_row(row: dict[str, Any], store: str | None = None) -> bool:
    """True when row matches library noise rules (tag or title/metadata heuristics)."""
    if is_catalog_noise_row(row):
        return True
    store_key = str(store or row.get("store") or "").lower()
    if store_key == "nintendo":
        return is_nintendo_noise_row(row)
    name = str(row.get("name") or "")
    if store_key == "psn":
        return should_auto_hide_psn_title(name)
    if store_key == "gog":
        return should_auto_hide_gog_title(name)
    return should_auto_hide_by_title(name)


def maybe_tag_library_noise_row(row: dict[str, Any], store: str | None = None) -> bool:
    """Tag row with ``noise`` when it matches library noise rules; returns True if tagged."""
    if is_library_noise_row(row, store):
        tag_noise_row(row)
        return True
    return False


def catalog_game_count(games: list[dict[str, Any]]) -> int:
    """Playable library size (rows without a ``noise`` tag)."""
    return sum(1 for g in games if not is_catalog_noise_row(g))


def tag_noise_row(row: dict[str, Any]) -> None:
    """Mark a catalog row as library noise (UI auto-hides)."""
    tags = list(row.get("tags") or [])
    if "noise" not in tags:
        tags.append("noise")
    row["tags"] = tags
