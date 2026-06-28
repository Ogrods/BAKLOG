import re
from difflib import SequenceMatcher
from howlongtobeatpy import HowLongToBeat

def _normalize_name(name: str) -> str:
    name = name.lower()
    name = re.sub('[^\\w\\s]', '', name)
    name = re.sub('\\s+', ' ', name).strip()
    return name

def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize_name(a), _normalize_name(b)).ratio()

class HltbClient:

    def __init__(self):
        self._client = HowLongToBeat()

    def lookup(self, game_name: str) -> dict | None:
        results = self._client.search(game_name)
        if not results:
            return None
        best = max(results, key=lambda r: _similarity(game_name, r.game_name))
        confidence = _similarity(game_name, best.game_name)
        return {'hltb_id': best.game_id, 'hltb_name': best.game_name, 'hltb_main_hours': _to_hours(best.main_story), 'hltb_main_extra_hours': _to_hours(best.main_extra), 'hltb_completionist_hours': _to_hours(best.completionist), 'hltb_match_confidence': round(confidence, 3)}

def _to_hours(value) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 1)
    except (TypeError, ValueError):
        return None