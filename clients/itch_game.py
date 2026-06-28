from __future__ import annotations
ITCH_NON_GAME_CLASSIFICATIONS = frozenset({'tool', 'assets', 'asset_pack', 'comic', 'book', 'soundtrack', 'physical_game', 'other'})

def itch_is_videogame(row: dict) -> bool:
    c = (row.get('classification') or '').strip().lower()
    if not c:
        return True
    return c not in ITCH_NON_GAME_CLASSIFICATIONS