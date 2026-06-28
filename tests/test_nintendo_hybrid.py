from __future__ import annotations
from fetchers.nintendo_hybrid import find_existing_row, index_existing_rows, is_nintendo_playable_game, match_nintendo_title_key, merge_vgc_with_transactions, nintendo_store_url

def _sample_vgc(**overrides) -> dict:
    base = {'application_id': '0100abc', 'vgc_id': 'vgc-1', 'name': 'Zelda Tears', 'platform': 'Nintendo Switch', 'apparent_platform': 'NX', 'publisher': 'Nintendo', 'icon_url': 'https://img.test/icon-hd.png', 'icon_url_standard': 'https://img.test/icon.png', 'is_dlc': False, 'is_lending': False, 'has_nx_application': True, 'contains_released': True}
    base.update(overrides)
    return base

def test_merge_vgc_with_transactions_joins_by_title() -> None:
    vgc = [_sample_vgc()]
    tx = [{'name': 'Zelda Tears', 'id': 'tx-99', 'nintendo_id': 'tx-99', 'purchase_date': '2024-01-01', 'device_type': 'HAC', 'tags': []}]
    merged = merge_vgc_with_transactions(vgc, tx)
    assert len(merged) == 1
    row = merged[0]
    assert row['id'] == '0100abc'
    assert row['name'] == 'Zelda Tears'
    assert row['application_id'] == '0100abc'
    assert row['nintendo_id'] == 'tx-99'
    assert row['purchase_date'] == '2024-01-01'
    assert row['ownership_source'] == 'both'
    assert row['icon_url'] == 'https://img.test/icon-hd.png'
    assert row['publisher'] == 'Nintendo'
    assert row['nintendo_platform'] == 'Nintendo Switch'

def test_merge_vgc_primary_lists_all_entitlements_before_orphan_receipts() -> None:
    vgc = [_sample_vgc(application_id='0100a', name='Alpha'), _sample_vgc(application_id='0100b', name='Beta')]
    tx = [{'name': 'Alpha', 'id': 'tx-a', 'nintendo_id': 'tx-a', 'purchase_date': '2024-01-01', 'tags': []}, {'name': 'Receipt Only', 'id': 'tx-only', 'nintendo_id': 'tx-only', 'purchase_date': '2025-01-01', 'tags': []}]
    merged = merge_vgc_with_transactions(vgc, tx)
    assert len(merged) == 3
    assert merged[0]['application_id'] == '0100a'
    assert merged[1]['application_id'] == '0100b'
    assert merged[2]['id'] == 'tx-only'
    assert merged[2]['ownership_source'] == 'transaction'

def test_merge_vgc_with_transactions_adds_vgc_only_entitlements() -> None:
    vgc = [_sample_vgc(application_id='0100old', vgc_id='vgc-old', name='Legacy Cartridge Port')]
    tx = [{'name': 'Recent Buy', 'id': 'tx-1', 'nintendo_id': 'tx-1', 'purchase_date': '2025-06-01', 'tags': []}]
    merged = merge_vgc_with_transactions(vgc, tx)
    assert len(merged) == 2
    assert merged[0]['ownership_source'] == 'vgc'
    assert merged[0]['purchase_date'] is None
    assert merged[1]['ownership_source'] == 'transaction'

def test_merge_vgc_tags_lending() -> None:
    vgc = [_sample_vgc(is_lending=True)]
    merged = merge_vgc_with_transactions(vgc, [])
    assert merged[0]['tags'] == ['lending']

def test_merge_vgc_tags_pure_dlc_entitlements() -> None:
    vgc = [_sample_vgc(is_dlc=True, is_lending=True, application_id='dlc-1')]
    merged = merge_vgc_with_transactions(vgc, [])
    assert len(merged) == 1
    assert 'noise' in merged[0]['tags']

def test_merge_vgc_fuzzy_matches_trademark_and_edition_titles() -> None:
    vgc = [_sample_vgc(name='Samba de Amigo: Party Central')]
    tx = [{'name': 'Samba de Amigo : Party Central Digital Deluxe Edition', 'id': 'tx-deluxe', 'nintendo_id': 'tx-deluxe', 'purchase_date': '2024-06-01', 'tags': []}]
    merged = merge_vgc_with_transactions(vgc, tx)
    assert len(merged) == 1
    assert merged[0]['ownership_source'] == 'both'
    assert merged[0]['purchase_date'] == '2024-06-01'

def test_match_nintendo_title_key_strips_deluxe_suffix() -> None:
    assert match_nintendo_title_key('Game Digital Deluxe Edition') == 'game'

def test_is_nintendo_playable_game_rejects_skins_and_dlc() -> None:
    assert is_nintendo_playable_game({'name': 'LEGO Sonic Skin', 'tags': []}) is False
    assert is_nintendo_playable_game({'name': 'Zelda', 'is_dlc': True}) is False
    assert is_nintendo_playable_game({'name': 'Zelda', 'tags': [], 'application_id': 'x'}) is True
    assert is_nintendo_playable_game({'name': 'Persona 5 Tactica: Orpheus Picaro & Izanagi Picaro', 'tags': []}) is False
    assert is_nintendo_playable_game({'name': 'SONIC SUPERSTARS Digital Art Book with Mini Digital Sound', 'tags': []}) is False

def test_nintendo_store_url_prefers_application_id() -> None:
    url = nintendo_store_url('01008F600B514000', 'Some Game')
    assert url.endswith('/game/01008F600B514000/')

def test_find_existing_row_matches_application_id_after_id_migration() -> None:
    existing = {'tx-old': {'id': 'tx-old', 'nintendo_id': 'tx-old', 'name': 'Shared Game', 'hltb_main_hours': 12}}
    by_title, by_app_id, by_nintendo_id = index_existing_rows(existing)
    cached = find_existing_row({'id': '0100abc', 'application_id': '0100abc', 'nintendo_id': 'tx-old', 'name': 'Shared Game'}, existing=existing, by_title=by_title, by_app_id=by_app_id, by_nintendo_id=by_nintendo_id)
    assert cached is not None
    assert cached['hltb_main_hours'] == 12