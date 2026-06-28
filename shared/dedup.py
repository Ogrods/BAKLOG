from __future__ import annotations
import re
_EDITION_WORDS = re.compile('\\b(remastered|edition|complete|gold|definitive|enhanced|classic|goty|of the year|game of the year|special|standard|deluxe|collection|anthology|pack|the)\\b')

def normalize_name_for_dedup(name: str | None) -> str:
    s = str(name or '').lower()
    s = s.replace('™', '').replace('®', '').replace('©', '')
    s = re.sub('[^a-z0-9]+', ' ', s)
    s = _EDITION_WORDS.sub(' ', s)
    return re.sub('\\s+', ' ', s).strip()