from shared.json_util import slim_games_payload, slim_row

def test_slim_row_drops_null_hltb_stubs():
    row = {'id': 1, 'name': 'Test', 'hltb_main_hours': None, 'tags': []}
    out = slim_row(row)
    assert 'hltb_main_hours' not in out
    assert out['name'] == 'Test'
    assert out['tags'] == []

def test_slim_row_keeps_non_null_enrichment():
    row = {'id': 1, 'hltb_main_hours': 12.5, 'steam_review_percent': None}
    out = slim_row(row)
    assert out['hltb_main_hours'] == 12.5
    assert 'steam_review_percent' not in out

def test_slim_games_payload():
    payload = {'store': 'steam', 'games': [{'id': 1, 'steam_review_percent': None, 'name': 'Game'}]}
    out = slim_games_payload(payload)
    assert 'steam_review_percent' not in out['games'][0]
    assert out['games'][0]['name'] == 'Game'