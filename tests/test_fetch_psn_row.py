from __future__ import annotations
from clients.psn_client import PsnGameEntry
from fetchers.fetch_psn import _build_game_row

def test_build_game_row_persists_play_count_without_sessions_tag() -> None:
    entry = PsnGameEntry(id='NPWR12345_00', np_communication_id='NPWR12345_00', title_id='CUSA12345_00', concept_id='10001234', name='Test Game', playtime_minutes=90, last_played='2024-01-01T00:00:00Z', first_played='2020-01-01T00:00:00Z', image_url='https://example.com/icon.png', platforms=['PS4', 'PS5'], trophy_progress=55, trophies_earned=10, trophies_total=20, has_platinum=True, platinum_earned=False, play_count=12, store_url='https://store.playstation.com/en-us/concept/10001234')
    row = _build_game_row(entry, None)
    assert row['play_count'] == 12
    assert row['first_played'] == '2020-01-01T00:00:00Z'
    assert row['psn_platforms'] == ['PS4', 'PS5']
    assert not any((t.startswith('Sessions ') for t in row['tags']))
    assert any((t.startswith('Trophy ') for t in row['tags']))