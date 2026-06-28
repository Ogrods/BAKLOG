from __future__ import annotations
import json
from pathlib import Path
import pytest
import fetchers.fetch_amazon as fa

def _launcher_row(pid: str, *, name: str='Launcher Game', asin: str | None='B00LAUNCH', last_played: str | None='2024-01-01') -> dict:
    return {'store': 'amazon', 'id': pid, 'amazon_id': pid, 'name': name, 'source': 'launcher', 'asin': asin, 'last_played': last_played, 'genres': ['Action'], 'header_image': 'https://launcher.example/icon.jpg'}

def _web_row(pid: str, *, name: str='Launcher Game', asin: str | None='B00LAUNCH') -> dict:
    return {'store': 'amazon', 'id': pid, 'amazon_id': pid, 'name': name, 'source': 'web', 'asin': asin, 'product_line': 'prime_claim', 'header_image': None}

class TestEffectiveRowSource:

    def test_legacy_row_treated_as_launcher(self) -> None:
        assert fa._effective_row_source({'name': 'Old'}) == 'launcher'

    def test_tagged_web(self) -> None:
        assert fa._effective_row_source({'source': 'web'}) == 'web'

class TestMergeAmazonSources:

    def test_union_keeps_both_slices(self) -> None:
        current = [_web_row('web-only', name='Prime Only', asin='B00WEB')]
        carried = [_launcher_row('launcher-only', name='Launcher Only', asin='B00ONLY')]
        out = fa.merge_amazon_sources(current, carried, 'web')
        names = {g['name'] for g in out}
        assert names == {'Prime Only', 'Launcher Only'}

    def test_asin_collapse_prefers_launcher(self) -> None:
        current = [_web_row('web-id-1', name='Same Game', asin='B00SAME')]
        carried = [_launcher_row('launcher-id-1', name='Same Game', asin='B00SAME', last_played='2024-06-01')]
        out = fa.merge_amazon_sources(current, carried, 'web')
        assert len(out) == 1
        assert out[0]['id'] == 'launcher-id-1'
        assert out[0]['last_played'] == '2024-06-01'
        assert out[0]['source'] == 'launcher'

    def test_launcher_winner_keeps_web_enrichment(self) -> None:
        web = _web_row('web-1', name='Prime Game', asin='B00ENR')
        web.update({'steam_review_percent': 75, 'steam_review_count': 500, 'coop_online': True, 'hltb_main_hours': 8.0})
        launcher = _launcher_row('launcher-1', name='Prime Game', asin='B00ENR')
        out = fa.merge_amazon_sources([launcher], [web], 'launcher')
        assert len(out) == 1
        row = out[0]
        assert row['source'] == 'launcher'
        assert row['steam_review_percent'] == 75
        assert row['steam_review_count'] == 500
        assert row['coop_online'] is True
        assert row['hltb_main_hours'] == 8.0

    def test_name_collapse_when_asin_missing(self) -> None:
        current = [_web_row('web-2', name='  Mystery   Game ', asin=None)]
        carried = [_launcher_row('launcher-2', name='mystery game', asin=None)]
        out = fa.merge_amazon_sources(current, carried, 'web')
        assert len(out) == 1
        assert out[0]['id'] == 'launcher-2'

class TestRefuseAmazonSourceDrift:

    def test_web_slice_shrink_triggers_exit_3(self, tmp_path: Path, monkeypatch) -> None:
        catalog = tmp_path / 'games_amazon.json'
        catalog.write_text(json.dumps({'games': [_web_row(f'w{i}', name=f'Web {i}', asin=f'B{i:03d}') for i in range(10)]}), encoding='utf-8')
        monkeypatch.setattr(fa, 'catalog_file', lambda p: catalog if p == fa.GAMES_AMAZON_JSON else tmp_path / p)
        assert fa.refuse_amazon_source_drift(2, source='web', allow_drift=False, output_path=fa.GAMES_AMAZON_JSON) == 3

    def test_launcher_slice_unchanged_does_not_block_web_run(self, tmp_path: Path, monkeypatch) -> None:
        catalog = tmp_path / 'games_amazon.json'
        catalog.write_text(json.dumps({'games': [_launcher_row(f'l{i}', name=f'Launcher {i}', asin=f'L{i:03d}') for i in range(20)]}), encoding='utf-8')
        monkeypatch.setattr(fa, 'catalog_file', lambda p: catalog if p == fa.GAMES_AMAZON_JSON else tmp_path / p)
        assert fa.refuse_amazon_source_drift(5, source='web', allow_drift=False, output_path=fa.GAMES_AMAZON_JSON) is None

class TestCarryForwardLogic:

    def test_legacy_rows_carried_on_web_run(self) -> None:
        existing = {'legacy-1': {'id': 'legacy-1', 'name': 'Old Launcher Title', 'asin': 'B00OLD'}}
        carried = [row for row in existing.values() if fa._effective_row_source(row) != 'web']
        assert len(carried) == 1
        assert carried[0]['name'] == 'Old Launcher Title'

    def test_same_source_not_carried(self) -> None:
        existing = {'w1': _web_row('w1', name='Web Title', asin='B1')}
        carried = [row for row in existing.values() if fa._effective_row_source(row) != 'web']
        assert carried == []

class TestResolveSourceLauncherDisabled:

    def test_launcher_db_ready_false_when_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(fa, 'is_local_provider_disabled', lambda provider: True)
        assert fa._launcher_db_ready(None) is False

    def test_auto_skips_launcher_when_user_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(fa, 'is_local_provider_disabled', lambda provider: provider == 'amazon')
        monkeypatch.setattr(fa, '_launcher_db_ready', lambda sql_dir: False)
        monkeypatch.setattr(fa, '_web_profile_ready', lambda: True)
        assert fa.resolve_source('auto', None) == 'web'

    def test_auto_launcher_when_not_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(fa, 'is_local_provider_disabled', lambda provider: False)
        monkeypatch.setattr(fa, '_launcher_db_ready', lambda sql_dir: True)
        assert fa.resolve_source('auto', None) == 'launcher'

    def test_auto_launcher_when_both_launcher_and_web_ready(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(fa, 'is_local_provider_disabled', lambda provider: False)
        monkeypatch.setattr(fa, '_launcher_db_ready', lambda sql_dir: True)
        monkeypatch.setattr(fa, '_web_profile_ready', lambda: True)
        assert fa.resolve_source('auto', None) == 'launcher'