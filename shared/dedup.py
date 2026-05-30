"""Cross-store dedup name normalization (mirrors dashboard logic)."""

from __future__ import annotations

import re

_EDITION_WORDS = re.compile(
    r"\b(remastered|edition|complete|gold|definitive|enhanced|classic|goty|"
    r"of the year|game of the year|special|standard|deluxe|collection|"
    r"anthology|pack|the)\b"
)


def normalize_name_for_dedup(name: str | None) -> str:
    s = str(name or "").lower()
    s = s.replace("\u2122", "").replace("\u00ae", "").replace("\u00a9", "")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = _EDITION_WORDS.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()
