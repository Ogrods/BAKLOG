_COUNTRY_CURRENCY = {
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
_STEAM_CURRENCY = {
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
_SYMBOLS = {
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "CAD": "C$",
    "AUD": "A$",
    "NZD": "NZ$",
    "JPY": "¥",
    "KRW": "₩",
    "CNY": "¥",
    "INR": "₹",
    "BRL": "R$",
    "MXN": "MX$",
    "NOK": "kr",
    "SEK": "kr",
    "DKK": "kr",
    "PLN": "zł",
    "CHF": "CHF ",
    "RUB": "₽",
    "TRY": "₺",
    "ZAR": "R",
}


def normalize_currency_code(code, *, country=None):
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


def country_to_currency(country):
    if not country:
        return "USD"
    key = str(country).strip().upper()
    return _COUNTRY_CURRENCY.get(key, "USD")


def currency_symbol(code):
    c = normalize_currency_code(code)
    sym = _SYMBOLS.get(c)
    if sym:
        return sym
    return f"{c} "


def format_price(amount, code=None, *, country=None):
    if amount is None:
        return None
    try:
        num = float(amount)
    except (TypeError, ValueError):
        return None
    if not num == num:
        return None
    cur = normalize_currency_code(code, country=country)
    sym = currency_symbol(cur)
    if cur in ("JPY", "KRW"):
        return f"{sym}{round(num):,}"
    if abs(num % 1) < 0.005:
        return f"{sym}{int(round(num))}"
    return f"{sym}{num:.2f}"
