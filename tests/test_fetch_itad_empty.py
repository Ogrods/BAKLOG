from __future__ import annotations
import json
from pathlib import Path
import pytest
import fetchers.fetch_itad as fetch_itad

@pytest.fixture
def _isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    catalogs = tmp_path / 'catalogs'
    catalogs.mkdir()

    def _catalog_path(name) -> Path:
        return catalogs / str(name)
    monkeypatch.setattr(fetch_itad, 'catalog_path', _catalog_path)
    monkeypatch.setattr(fetch_itad, 'itad_path', lambda: catalogs / 'itad_prices.json')
    monkeypatch.setattr(fetch_itad, 'resolve_env', lambda *a, **k: 'test-key')
    monkeypatch.setattr(fetch_itad, 'ensure_fx_rates', lambda **k: None)
    monkeypatch.setattr(fetch_itad, 'ItadClient', lambda *a, **k: pytest.fail('ItadClient should not be built for an empty wishlist'))
    monkeypatch.setattr('sys.argv', ['fetchers.fetch_itad.py'])
    return catalogs

def test_empty_wishlist_warns_and_exits_clean(_isolated: Path, capsys):
    exit_code = fetch_itad.main()
    assert exit_code == 0
    out = capsys.readouterr()
    combined = out.out + out.err
    assert 'wishlist is empty' in combined.lower()
    assert 'skipping ITAD price fetch' in combined

def test_empty_wishlist_does_not_overwrite_existing_prices(_isolated: Path):
    existing = _isolated / 'itad_prices.json'
    prior = {'count': 3, 'by_key': {'wishlist:1': {'price': 9.99}}}
    existing.write_text(json.dumps(prior), encoding='utf-8')
    exit_code = fetch_itad.main()
    assert exit_code == 0
    assert json.loads(existing.read_text(encoding='utf-8')) == prior