"""Shared Steam title matching helpers (storesearch selection, giveaway title cleanup).

Sync pair: strip_giveaway_decorations ↔ js/claimable.js stripClaimTitleDecorations
"""

from __future__ import annotations

import re

_STEAM_APP_URL = re.compile(
    r"store\.steampowered\.com/app/(?P<appid>\d+)",
    re.IGNORECASE,
)

_NUMBER_TOKENS = re.compile(r"\b(\d+)\b")

_SPINOFF_MARKERS = re.compile(
    r"\b(director|artbook|soundtrack|wallpaper|dlc|upgrade|deluxe|bundle|pack|skin|ost"
    r"|ascended|relaunched|reloaded)\b"
)


def strip_giveaway_decorations(title: str) -> str:
    """Strip giveaway/store boilerplate from auto-sourced claim titles."""
    t = str(title or "").strip()
    if not t:
        return t
    t = re.sub(r"\s*\([^)]*\)\s*giveaway\s*$", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s+free\s+(at\s+egs\s+)?on\s+epic\s+game\s+store.*$", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s+free\s+for\s+mobile\s+on\s+egs.*$", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s+in\s+game\s+(items?|currency\s+pack).*$", "", t, flags=re.IGNORECASE)
    t = re.sub(
        r"\s+free\s+on\s+(steam|itchio|itch\.io|gog|indiegala).*$",
        "",
        t,
        flags=re.IGNORECASE,
    )
    t = re.sub(r"\s*-\s*free\s+on\s+indiegala.*$", "", t, flags=re.IGNORECASE)
    t = re.sub(
        r"\s+on\s+(steam|gog|itch\.?io|epic\s+game\s+store)\s*$",
        "",
        t,
        flags=re.IGNORECASE,
    )
    t = re.sub(r"\s+-\s+chapters?[\s\d,]+.*$", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s+giveaway\s*$", "", t, flags=re.IGNORECASE)
    return t.strip()


def normalize_title(name: str) -> str:
    s = (name or "").lower()
    s = re.sub(r"[\u2122\u00ae\u00a9]", "", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(
        r"\b(remastered|edition|complete|gold|definitive|enhanced|classic|goty|"
        r"of the year|game of the year|special|standard|deluxe|collection|"
        r"anthology|pack|the|hd|remake)\b",
        " ",
        s,
    )
    return re.sub(r"\s+", " ", s).strip()


def _number_tokens(s: str) -> set[str]:
    return set(_NUMBER_TOKENS.findall(s))


def close_enough_title(target: str, candidate: str) -> bool:
    """Substring fallback for Steam store search — reject sequels and spin-offs."""
    if not candidate:
        return False
    if candidate == target:
        return True
    if candidate not in target and target not in candidate:
        return False
    if _number_tokens(candidate) - _number_tokens(target):
        return False
    if not candidate.startswith(target):
        return False
    suffix = candidate[len(target) :].strip()
    if not suffix:
        return True
    if _SPINOFF_MARKERS.search(suffix):
        return False
    return len(suffix.split()) <= 2


def pick_appid(items: list[dict], name: str) -> int | None:
    """Pick the most likely Steam appid from storesearch items (no network)."""
    if not items:
        return None
    target = normalize_title(name)
    for item in items:
        if normalize_title(str(item.get("name") or "")) == target:
            try:
                return int(item["id"])
            except (KeyError, TypeError, ValueError):
                continue
    first = items[0]
    first_norm = normalize_title(str(first.get("name") or ""))
    if first_norm and close_enough_title(target, first_norm):
        try:
            return int(first["id"])
        except (KeyError, TypeError, ValueError):
            return None
    return None


def appid_from_steam_url(url: str) -> int | None:
    """Extract Steam appid from a store.steampowered.com/app/<id> URL."""
    m = _STEAM_APP_URL.search(str(url or ""))
    if not m:
        return None
    try:
        return int(m.group("appid"))
    except (TypeError, ValueError):
        return None
