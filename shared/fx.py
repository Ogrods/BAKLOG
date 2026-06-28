from __future__ import annotations
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from shared.money import normalize_currency_code
from shared.profile_paths import fx_rates_path
FRANKFURTER_LATEST = 'https://api.frankfurter.app/latest'
CACHE_MAX_AGE_SECONDS = 24 * 3600
STALE_WARN_SECONDS = 7 * 24 * 3600
CACHE_HARD_MAX_AGE_SECONDS = 30 * 24 * 3600
_ZERO_DECIMAL = frozenset({'JPY', 'KRW'})

def round_amount(amount: float, currency: str) -> float:
    cur = normalize_currency_code(currency)
    if cur in _ZERO_DECIMAL:
        return float(round(amount))
    return round(amount, 2)

def parse_price_amount(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        num = float(value)
        return num if num == num else None
    m = re.search('-?\\d+(?:\\.\\d+)?', str(value))
    if not m:
        return None
    try:
        return float(m.group())
    except ValueError:
        return None

def _parse_fetched_at(doc: dict[str, Any]) -> datetime | None:
    raw = doc.get('fetched_at')
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace('Z', '+00:00'))
    except ValueError:
        return None

def _cache_age_seconds(doc: dict[str, Any]) -> float | None:
    ts = _parse_fetched_at(doc)
    if ts is None:
        return None
    now = datetime.now(UTC)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return (now - ts).total_seconds()

def load_fx_rates(*, profile_id: str | None=None) -> dict[str, Any] | None:
    path = fx_rates_path(profile_id=profile_id)
    if not path.exists():
        return None
    try:
        doc = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(doc, dict) or not doc.get('rates'):
        return None
    return doc

def _fetch_from_api() -> dict[str, Any]:
    req = urllib.request.Request(FRANKFURTER_LATEST, headers={'Accept': 'application/json', 'User-Agent': 'steam-backlog/1.0'})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode('utf-8')
    data = json.loads(raw)
    base = str(data.get('base') or 'EUR').upper()
    rates_in = data.get('rates') or {}
    rates: dict[str, float] = {base: 1.0}
    for code, val in rates_in.items():
        if isinstance(val, (int, float)):
            rates[str(code).upper()] = float(val)
    return {'fetched_at': datetime.now(UTC).isoformat(), 'source': 'frankfurter', 'date': data.get('date'), 'base': base, 'rates': rates}

def _warn_stale_fx_cache(age: float) -> None:
    print(f'WARN: FX rates are {int(age / 86400)}d old (>{STALE_WARN_SECONDS // 86400}d); re-run fetch_itad to refresh.', file=sys.stderr, flush=True)

def _return_cached_or_raise(cached: dict[str, Any], age: float | None, *, warn_stale: bool, err: Exception | None=None) -> dict[str, Any]:
    if age is not None and age > CACHE_HARD_MAX_AGE_SECONDS:
        detail = f' ({err})' if err else ''
        raise RuntimeError(f'FX cache too old ({int(age / 86400)}d) and refresh failed{detail}')
    if warn_stale and age is not None and (age >= STALE_WARN_SECONDS):
        _warn_stale_fx_cache(age)
    if err is not None:
        print(f'WARN: FX fetch failed ({err}); using cached rates.', file=sys.stderr, flush=True)
    return cached

def save_fx_rates(doc: dict[str, Any], *, profile_id: str | None=None) -> Path:
    path = fx_rates_path(profile_id=profile_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)
    return path

def ensure_fx_rates(*, force: bool=False, warn_stale: bool=True, profile_id: str | None=None) -> dict[str, Any]:
    cached = None if force else load_fx_rates(profile_id=profile_id)
    age = _cache_age_seconds(cached) if cached else None
    if cached and age is not None and (age < CACHE_MAX_AGE_SECONDS):
        return cached
    try:
        doc = _fetch_from_api()
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        if cached:
            return _return_cached_or_raise(cached, age, warn_stale=warn_stale, err=e)
        raise RuntimeError(f'FX rate fetch failed and no cache: {e}') from e
    save_fx_rates(doc, profile_id=profile_id)
    print(f"FX rates refreshed ({doc.get('date') or 'latest'}, base {doc.get('base')}, {len(doc.get('rates') or {})} pairs).", flush=True)
    return doc

def convert(amount: float, from_ccy: str, to_ccy: str, rates_doc: dict[str, Any]) -> float | None:
    src = normalize_currency_code(from_ccy)
    dst = normalize_currency_code(to_ccy)
    if src == dst:
        return round_amount(float(amount), dst)
    rates = rates_doc.get('rates') or {}
    base = normalize_currency_code(str(rates_doc.get('base') or 'EUR'))
    try:
        amount_f = float(amount)
    except (TypeError, ValueError):
        return None
    if not rates:
        return None

    def to_base(cur: str, val: float) -> float | None:
        if cur == base:
            return val
        rate = rates.get(cur)
        if rate is None or rate == 0:
            return None
        return val / float(rate)

    def from_base(cur: str, val: float) -> float | None:
        if cur == base:
            return val
        rate = rates.get(cur)
        if rate is None:
            return None
        return val * float(rate)
    in_base = to_base(src, amount_f)
    if in_base is None:
        return None
    out = from_base(dst, in_base)
    if out is None:
        return None
    return round_amount(out, dst)