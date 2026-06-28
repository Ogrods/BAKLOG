from datetime import UTC, datetime, timedelta
from shared.fx import CACHE_HARD_MAX_AGE_SECONDS, convert, ensure_fx_rates, parse_price_amount, round_amount
from shared.wishlist_fx import apply_fx_to_game

def _eur_base_rates() -> dict:
    return {'base': 'EUR', 'fetched_at': '2026-06-01T12:00:00+00:00', 'rates': {'EUR': 1.0, 'USD': 1.1, 'GBP': 0.85, 'JPY': 160.0}}

def test_parse_price_amount():
    assert parse_price_amount('£45.99') == 45.99
    assert parse_price_amount('$9.99') == 9.99
    assert parse_price_amount(12.5) == 12.5
    assert parse_price_amount(None) is None

def test_convert_gbp_to_usd():
    rates = _eur_base_rates()
    out = convert(10, 'GBP', 'USD', rates)
    assert out is not None
    assert abs(out - 10 / 0.85 * 1.1) < 0.02

def test_convert_same_currency():
    assert convert(9.99, 'USD', 'USD', _eur_base_rates()) == 9.99

def test_convert_missing_pair():
    assert convert(10, 'GBP', 'XYZ', _eur_base_rates()) is None

def test_round_amount_jpy():
    assert round_amount(1234.6, 'JPY') == 1235.0
    assert round_amount(9.999, 'USD') == 10.0

def test_apply_fx_to_game_preserves_native():
    rates = _eur_base_rates()
    game = {'name': 'Test', 'currency': 'GBP', 'price': '£45.00', 'price_initial': '£60.00'}
    assert apply_fx_to_game(game, 'USD', rates) is True
    assert game['currency_native'] == 'GBP'
    assert game['price_native'] == '£45.00'
    assert game['currency'] == 'USD'
    assert game['price_amount'] is not None
    assert game['fx_converted'] is True

def test_apply_fx_is_idempotent():
    rates = _eur_base_rates()
    game = {'currency': 'GBP', 'price': '£45.00', 'price_initial': '£60.00'}
    assert apply_fx_to_game(game, 'USD', rates) is True
    first = dict(game)
    assert apply_fx_to_game(game, 'USD', rates) is False
    assert game == first

def test_apply_fx_no_double_conversion_on_target_change():
    rates = _eur_base_rates()
    native = {'currency': 'GBP', 'price': '£45.00', 'price_initial': '£60.00'}
    apply_fx_to_game(native, 'USD', rates)
    direct = {'currency': 'GBP', 'price': '£45.00', 'price_initial': '£60.00'}
    apply_fx_to_game(direct, 'EUR', rates)
    changed = apply_fx_to_game(native, 'EUR', rates)
    assert changed is True
    assert native['currency_native'] == 'GBP'
    assert native['price_native'] == '£45.00'
    assert abs(native['price_amount'] - direct['price_amount']) < 0.001

def test_apply_fx_restores_native_when_target_matches():
    rates = _eur_base_rates()
    game = {'currency': 'GBP', 'price': '£45.00', 'price_initial': '£60.00'}
    apply_fx_to_game(game, 'USD', rates)
    assert apply_fx_to_game(game, 'GBP', rates) is True
    assert game['currency'] == 'GBP'
    assert game['price'] == '£45.00'
    assert 'currency_native' not in game
    assert 'price_amount' not in game
    assert 'fx_converted' not in game

def test_apply_fx_same_currency_is_noop():
    rates = _eur_base_rates()
    game = {'currency': 'USD', 'price': '$9.99'}
    assert apply_fx_to_game(game, 'USD', rates) is False
    assert game == {'currency': 'USD', 'price': '$9.99'}

def test_apply_fx_missing_pair_leaves_native():
    rates = _eur_base_rates()
    game = {'currency': 'XYZ', 'price': '10.00'}
    assert apply_fx_to_game(game, 'USD', rates) is False
    assert game['currency'] == 'XYZ'
    assert 'price_amount' not in game

def test_apply_fx_refuses_corrupted_fx_converted_row():
    rates = _eur_base_rates()
    game = {'fx_converted': True, 'currency': 'USD', 'price': '$58.00'}
    assert apply_fx_to_game(game, 'EUR', rates) is False

def test_ensure_fx_rates_warns_on_stale_cache_fallback(monkeypatch, tmp_path):
    import shared.fx as fx_mod
    old = (datetime.now(UTC) - timedelta(days=10)).isoformat()
    doc = {**_eur_base_rates(), 'fetched_at': old}
    path = tmp_path / 'fx_rates.json'
    path.write_text(__import__('json').dumps(doc), encoding='utf-8')
    monkeypatch.setattr(fx_mod, 'fx_rates_path', lambda **_: path)
    monkeypatch.setattr(fx_mod, '_fetch_from_api', lambda: (_ for _ in ()).throw(OSError('offline')))
    out = ensure_fx_rates(warn_stale=True)
    assert out['base'] == 'EUR'

def test_ensure_fx_rates_refuses_ancient_cache(monkeypatch, tmp_path):
    import shared.fx as fx_mod
    days = CACHE_HARD_MAX_AGE_SECONDS // 86400 + 1
    old = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    doc = {**_eur_base_rates(), 'fetched_at': old}
    path = tmp_path / 'fx_rates.json'
    path.write_text(__import__('json').dumps(doc), encoding='utf-8')
    monkeypatch.setattr(fx_mod, 'fx_rates_path', lambda **_: path)
    monkeypatch.setattr(fx_mod, '_fetch_from_api', lambda: (_ for _ in ()).throw(OSError('offline')))
    try:
        ensure_fx_rates(warn_stale=True)
        assert False, 'expected RuntimeError'
    except RuntimeError as e:
        assert 'too old' in str(e).lower()