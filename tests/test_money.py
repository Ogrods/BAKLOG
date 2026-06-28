"""Tests for shared/money.py."""

from shared.money import (
    country_to_currency,
    currency_symbol,
    format_price,
    normalize_currency_code,
)


def test_country_to_currency():
    assert country_to_currency("US") == "USD"
    assert country_to_currency("GB") == "GBP"
    assert country_to_currency("DE") == "EUR"
    assert country_to_currency("xx") == "USD"
    assert country_to_currency(None) == "USD"


def test_normalize_steam_currency():
    assert normalize_currency_code("eur") == "EUR"
    assert normalize_currency_code("gbp") == "GBP"


def test_currency_symbol():
    assert currency_symbol("USD") == "$"
    assert currency_symbol("EUR") == "\u20ac"
    assert currency_symbol("GBP") == "\u00a3"


def test_format_price():
    assert format_price(9.99, "USD") == "$9.99"
    assert format_price(12.5, "EUR") == "\u20ac12.50"
    assert format_price(10, "GBP") == "\u00a310"
    assert format_price(1200, "JPY") == "\u00a51,200"
    assert format_price(None, "USD") is None
