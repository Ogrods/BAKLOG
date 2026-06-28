"""Currency helpers for fetchers and ITAD — deterministic, no locale dependency."""

from __future__ import annotations

# ISO 3166-1 alpha-2 country -> ISO 4217 currency (common storefronts).
_COUNTRY_CURRENCY: dict[str, str] = {
    "US": "USD",
    "GB": "GBP",
    "UK": "GBP",
    "CA": "CAD",
    "AU": "AUD",
    "NZ": "NZD",
    "JP": "JPY",
    "KR": "KRW",
    "CN": "CNY",
    "IN": "INR",
    "BR": "BRL",
    "MX": "MXN",
    "NO": "NOK",
    "SE": "SEK",
    "DK": "DKK",
    "PL": "PLN",
    "CH": "CHF",
    "RU": "RUB",
    "TR": "TRY",
    "ZA": "ZAR",
    # Eurozone (ITAD / storefronts use these country codes)
    "DE": "EUR",
    "FR": "EUR",
    "IT": "EUR",
    "ES": "EUR",
    "NL": "EUR",
    "BE": "EUR",
    "AT": "EUR",
    "IE": "EUR",
    "PT": "EUR",
    "FI": "EUR",
    "GR": "EUR",
}

# Steam API currency codes (lowercase) -> ISO 4217
_STEAM_CURRENCY: dict[str, str] = {
    "usd": "USD",
    "eur": "EUR",
    "gbp": "GBP",
    "cad": "CAD",
    "aud": "AUD",
    "nzd": "NZD",
    "jpy": "JPY",
    "krw": "KRW",
    "cny": "CNY",
    "inr": "INR",
    "brl": "BRL",
    "mxn": "MXN",
    "nok": "NOK",
    "sek": "SEK",
    "dkk": "DKK",
    "pln": "PLN",
    "chf": "CHF",
    "rub": "RUB",
    "try": "TRY",
    "zar": "ZAR",
}

_SYMBOLS: dict[str, str] = {
    "USD": "$",
    "EUR": "\u20ac",
    "GBP": "\u00a3",
    "CAD": "C$",
    "AUD": "A$",
    "NZD": "NZ$",
    "JPY": "\u00a5",
    "KRW": "\u20a9",
    "CNY": "\u00a5",
    "INR": "\u20b9",
    "BRL": "R$",
    "MXN": "MX$",
    "NOK": "kr",
    "SEK": "kr",
    "DKK": "kr",
    "PLN": "z\u0142",
    "CHF": "CHF ",
    "RUB": "\u20bd",
    "TRY": "\u20ba",
    "ZAR": "R",
}


def normalize_currency_code(code: str | None, *, country: str | None = None) -> str:
    """Resolve a currency code from explicit code, Steam-style code, or country."""
    if code:
        raw = str(code).strip()
        if not raw:
            pass
        elif len(raw) == 3 and raw.isalpha():
            upper = raw.upper()
            if upper in _SYMBOLS:
                return upper
            steam = _STEAM_CURRENCY.get(raw.lower())
            if steam:
                return steam
            return upper
        steam = _STEAM_CURRENCY.get(raw.lower())
        if steam:
            return steam
    if country:
        return country_to_currency(country)
    return "USD"


def country_to_currency(country: str | None) -> str:
    if not country:
        return "USD"
    key = str(country).strip().upper()
    return _COUNTRY_CURRENCY.get(key, "USD")


def currency_symbol(code: str | None) -> str:
    c = normalize_currency_code(code)
    sym = _SYMBOLS.get(c)
    if sym:
        return sym
    return f"{c} "


def format_price(amount: float | int | None, code: str | None = None, *, country: str | None = None) -> str | None:
    if amount is None:
        return None
    try:
        num = float(amount)
    except (TypeError, ValueError):
        return None
    if not num == num:  # NaN
        return None
    cur = normalize_currency_code(code, country=country)
    sym = currency_symbol(cur)
    if cur in ("JPY", "KRW"):
        return f"{sym}{round(num):,}"
    if abs(num % 1) < 0.005:
        return f"{sym}{int(round(num))}"
    return f"{sym}{num:.2f}"
