import json
import os

from fetchers.registry import WISHLIST_JSON_BY_KEY
from shared.fx import convert, ensure_fx_rates, load_fx_rates, parse_price_amount
from shared.money import country_to_currency, format_price, normalize_currency_code
from shared.profile_paths import catalog_path, itad_path
from shared.safe_write import safe_write_text

WISHLIST_FILENAMES = tuple(sorted(set(WISHLIST_JSON_BY_KEY.values())))


def display_currency_for_profile(*, profile_id=None):
    ip = itad_path(profile_id=profile_id)
    if ip.exists():
        try:
            doc = json.loads(ip.read_text(encoding="utf-8"))
            cur = doc.get("currency")
            if cur:
                return normalize_currency_code(cur)
            country = doc.get("country")
            if country:
                return country_to_currency(country)
        except (OSError, json.JSONDecodeError):
            pass
    country = os.environ.get("ITAD_COUNTRY", "US").strip().upper() or "US"
    return country_to_currency(country)


_FX_FIELDS = (
    "currency",
    "price",
    "price_initial",
    "price_amount",
    "price_amount_initial",
    "currency_native",
    "price_native",
    "price_initial_native",
    "fx_converted",
)


def _snapshot(game):
    return tuple(game.get(k) for k in _FX_FIELDS)


def apply_fx_to_game(game, target_ccy, rates_doc):
    if not isinstance(game, dict):
        return False
    if game.get("fx_converted") and (not game.get("currency_native")):
        return False
    was_converted = bool(game.get("currency_native"))
    native_ccy = normalize_currency_code(game.get("currency_native") if was_converted else game.get("currency"))
    if not native_ccy:
        return False
    native_price = game.get("price_native") if was_converted else game.get("price")
    native_initial = game.get("price_initial_native") if was_converted else game.get("price_initial")
    amount = parse_price_amount(native_price)
    if amount is None:
        return False
    before = _snapshot(game)
    if native_ccy == target_ccy:
        if not was_converted and game.get("price_amount") is None:
            return False
        game["currency"] = native_ccy
        if native_price is not None:
            game["price"] = native_price
        if native_initial is not None:
            game["price_initial"] = native_initial
        for key in (
            "currency_native",
            "price_native",
            "price_initial_native",
            "price_amount",
            "price_amount_initial",
            "fx_converted",
        ):
            game.pop(key, None)
        return _snapshot(game) != before
    converted = convert(amount, native_ccy, target_ccy, rates_doc)
    if converted is None:
        return False
    game["currency_native"] = native_ccy
    if native_price is not None:
        game["price_native"] = native_price
    if native_initial is not None:
        game["price_initial_native"] = native_initial
    else:
        game.pop("price_initial_native", None)
    game["price_amount"] = converted
    game["price"] = format_price(converted, target_ccy)
    game["currency"] = target_ccy
    game["fx_converted"] = True
    initial_amount = parse_price_amount(native_initial)
    initial_conv = convert(initial_amount, native_ccy, target_ccy, rates_doc) if initial_amount is not None else None
    if initial_conv is not None:
        game["price_amount_initial"] = initial_conv
        game["price_initial"] = format_price(initial_conv, target_ccy)
    else:
        game.pop("price_amount_initial", None)
    return _snapshot(game) != before


def apply_fx_to_games(games, target_ccy, rates_doc):
    n = 0
    for g in games:
        if apply_fx_to_game(g, target_ccy, rates_doc):
            n += 1
    return n


def apply_fx_to_catalog_payload(payload, target_ccy, rates_doc):
    games = payload.get("games")
    if not isinstance(games, list):
        return 0
    n = apply_fx_to_games(games, target_ccy, rates_doc)
    if n:
        payload["display_currency"] = target_ccy
        payload["fx_rates_at"] = rates_doc.get("fetched_at")
        payload["fx_rates_date"] = rates_doc.get("date")
    return n


def apply_fx_to_wishlist_file(filename, target_ccy, rates_doc, *, profile_id=None):
    path = catalog_path(filename, profile_id=profile_id)
    if not path.exists():
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    if not isinstance(payload, dict):
        return 0
    n = apply_fx_to_catalog_payload(payload, target_ccy, rates_doc)
    if n:
        safe_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False))
    return n


def apply_fx_to_all_wishlist_files(target_ccy=None, rates_doc=None, *, profile_id=None):
    target = target_ccy or display_currency_for_profile(profile_id=profile_id)
    rates = rates_doc or load_fx_rates(profile_id=profile_id)
    if not rates:
        return (0, 0)
    files = 0
    rows = 0
    for name in WISHLIST_FILENAMES:
        n = apply_fx_to_wishlist_file(name, target, rates, profile_id=profile_id)
        if n:
            files += 1
            rows += n
    return (files, rows)


def refresh_wishlist_fx_after_itad(country, *, profile_id=None):
    target = country_to_currency(country)
    try:
        rates = ensure_fx_rates(profile_id=profile_id, warn_stale=True)
    except RuntimeError:
        rates = load_fx_rates(profile_id=profile_id)
    return apply_fx_to_all_wishlist_files(target, rates, profile_id=profile_id)
