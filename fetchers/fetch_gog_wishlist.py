import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
import requests
from dotenv import load_dotenv
from auth import mark_invalid, resolve_env
from auth.session_probe import probe_gog_session
from clients.gog_client import GogAuthError, GogClient
from clients.hltb_client import HltbClient
from fetchers._base import add_allow_empty_arg, add_only_new_arg, configure_stdout, load_existing_games, refuse_drift_result, refuse_empty_result, write_catalog_text
from fetchers._progress import EXIT_CODE_AUTH, RunStats, run_with_heartbeat, started
from shared.money import format_price
GAMES_WISHLIST_GOG_JSON = Path('games_wishlist_gog.json')
GOG_API_BASE = 'https://api.gog.com'
GOG_PRODUCT_DELAY_SEC = 0.4
HLTB_DELAY_SEC = 1.0

def _gog_image_urls(raw: str | None) -> tuple[str | None, str | None]:
    if not raw:
        return (None, None)
    url = raw
    if url.startswith('//'):
        url = 'https:' + url
    if not url.startswith('http'):
        return (None, None)
    if url.endswith('.jpg') or url.endswith('.png'):
        return (url, url)
    return (f'{url}.jpg', f'{url}_glx_vertical_cover.jpg')

def _fetch_wishlist_ids(gog: GogClient, refresh: bool) -> list[int]:
    from clients.gog_client import USER_STATE_TTL
    data = gog._get('/user/wishlist.json', refresh=refresh, cache_key='user_wishlist', max_age_seconds=USER_STATE_TTL)
    ids: list[int] = []
    wl = data.get('wishlist')
    if isinstance(wl, dict):
        for k in wl.keys():
            try:
                ids.append(int(k))
            except (TypeError, ValueError):
                continue
    if not ids and isinstance(data.get('products'), list):
        for item in data['products']:
            if isinstance(item, int):
                ids.append(item)
            elif isinstance(item, dict) and item.get('id') is not None:
                try:
                    ids.append(int(item['id']))
                except (TypeError, ValueError):
                    continue
    return ids

def _fetch_product(session: requests.Session, gog_id: int, country: str) -> dict | None:
    try:
        resp = session.get(f'{GOG_API_BASE}/products/{gog_id}', params={'expand': 'description,screenshots', 'locale': 'en-US', 'countryCode': country}, timeout=20)
        if resp.status_code != 200:
            snippet = (resp.text or '')[:120].replace('\n', ' ')
            print(f'  HTTP {resp.status_code} for {resp.url}: {snippet}', flush=True)
            return None
        return resp.json()
    except requests.RequestException as exc:
        print(f'  request failed for product {gog_id}: {exc}', flush=True)
        return None

def _fetch_price(session: requests.Session, gog_id: int, country: str) -> dict | None:
    try:
        resp = session.get(f'{GOG_API_BASE}/products/{gog_id}/prices', params={'countryCode': country}, timeout=20)
        if resp.status_code != 200:
            snippet = (resp.text or '')[:120].replace('\n', ' ')
            print(f'  HTTP {resp.status_code} for {resp.url}: {snippet}', flush=True)
            return None
        return resp.json()
    except requests.RequestException as exc:
        print(f'  request failed for price {gog_id}: {exc}', flush=True)
        return None

def _money_to_float(amount: str | int | float | None) -> float | None:
    if amount is None:
        return None
    try:
        s = str(amount)
        if s.isdigit():
            return int(s) / 100.0
        return float(s)
    except (TypeError, ValueError):
        return None

def _build_row(gog_id: int, product: dict | None, price_doc: dict | None, hltb_data: dict | None) -> dict:
    title = (product or {}).get('title') or f'GOG {gog_id}'
    image = (product or {}).get('image') or (product or {}).get('background_image')
    header_url, library_url = _gog_image_urls(image)
    release = (product or {}).get('release_date')
    slug = (product or {}).get('slug') or str(gog_id)
    final = None
    base = None
    discount = None
    currency = None
    price_str = None
    if price_doc:
        embedded = price_doc.get('_embedded') or {}
        prices_list = embedded.get('prices') or []
        if prices_list:
            best = prices_list[0]
            fp_raw = best.get('finalPrice')
            bp_raw = best.get('basePrice')
            final = _money_to_float(fp_raw.split(' ')[0] if isinstance(fp_raw, str) else fp_raw)
            base = _money_to_float(bp_raw.split(' ')[0] if isinstance(bp_raw, str) else bp_raw)
            currency = (best.get('currency') or {}).get('code') if isinstance(best.get('currency'), dict) else None
            if isinstance(best.get('finalPrice'), str) and ' ' in best['finalPrice']:
                currency = currency or best['finalPrice'].split(' ')[-1]
            if final is not None:
                price_str = f'${final:.2f}'
            if final is not None and base and (base > 0):
                discount = round(100 * (1 - final / base))
    cur_norm = currency or 'USD'
    return {'store': 'wishlist', 'wishlist_store': 'gog', 'id': gog_id, 'gog_id': gog_id, 'name': title, 'playtime_minutes': 0, 'last_played': None, 'header_image': header_url, 'library_image': library_url, 'release_date': release, 'genres': [], 'tags': [], 'steam_review_percent': None, 'steam_review_count': None, 'steam_review_desc': None, 'hltb_main_hours': (hltb_data or {}).get('hltb_main_hours'), 'hltb_main_extra_hours': (hltb_data or {}).get('hltb_main_extra_hours'), 'hltb_completionist_hours': (hltb_data or {}).get('hltb_completionist_hours'), 'hltb_match_confidence': (hltb_data or {}).get('hltb_match_confidence'), 'hltb_name': (hltb_data or {}).get('hltb_name'), 'store_url': f'https://www.gog.com/en/game/{slug}', 'type': 'game', 'price': price_str, 'price_initial': format_price(base, cur_norm) if base is not None else None, 'discount_percent': discount, 'currency': cur_norm}

def main() -> int:
    parser = argparse.ArgumentParser(description='Fetch GOG wishlist')
    parser.add_argument('--refresh', action='store_true', help='Ignore cached wishlist ID list')
    parser.add_argument('--country', default='US', help='GOG storefront country code (default US)')
    parser.add_argument('--hltb', action='store_true', help='Look up HLTB hours (slow)')
    add_only_new_arg(parser)
    add_allow_empty_arg(parser)
    args = parser.parse_args()
    configure_stdout()
    t0 = started('fetch_gog_wishlist')
    stats = RunStats()
    load_dotenv()
    gog_al = resolve_env('GOG_AL', provider='gog')
    if not gog_al:
        stats.error('Set GOG_AL in .env (see README for cookie instructions).')
        return stats.finish('fetch_gog_wishlist', t0, exit_code=1)
    probe_err = probe_gog_session(gog_al)
    if probe_err:
        mark_invalid('gog', error=probe_err)
        stats.error(probe_err)
        return stats.finish('fetch_gog_wishlist', t0, exit_code=EXIT_CODE_AUTH)
    gog = GogClient(gog_al)
    print('Fetching GOG wishlist IDs...', flush=True)
    try:
        ids = run_with_heartbeat(lambda: _fetch_wishlist_ids(gog, refresh=args.refresh), 'GOG wishlist capture')
    except GogAuthError as e:
        mark_invalid('gog', error=str(e))
        stats.error(str(e))
        return stats.finish('fetch_gog_wishlist', t0, exit_code=EXIT_CODE_AUTH)
    empty_exit = refuse_empty_result(ids, label='GOG wishlist', allow_empty=args.allow_empty, output_path=GAMES_WISHLIST_GOG_JSON)
    if empty_exit is not None:
        return stats.finish('fetch_gog_wishlist', t0, exit_code=empty_exit)
    drift_exit = refuse_drift_result(ids, label='GOG wishlist', allow_drift=args.allow_drift, output_path=GAMES_WISHLIST_GOG_JSON)
    if drift_exit is not None:
        return stats.finish('fetch_gog_wishlist', t0, exit_code=drift_exit)
    print(f'Found {len(ids)} GOG wishlist items.', flush=True)
    session = requests.Session()
    session.headers['User-Agent'] = 'steam-backlog/1.0'
    hltb = HltbClient() if args.hltb else None
    existing = load_existing_games(GAMES_WISHLIST_GOG_JSON)
    rows: list[dict] = []
    for i, gog_id in enumerate(ids, 1):
        cached = existing.get(str(gog_id))
        if args.only_new and cached:
            rows.append(cached)
            continue
        print(f'[{i}/{len(ids)}] product {gog_id}', flush=True)
        product = _fetch_product(session, gog_id, args.country)
        time.sleep(GOG_PRODUCT_DELAY_SEC)
        price_doc = _fetch_price(session, gog_id, args.country)
        time.sleep(GOG_PRODUCT_DELAY_SEC)
        hltb_data = None
        if hltb and product and product.get('title'):
            try:
                time.sleep(HLTB_DELAY_SEC)
                hltb_data = hltb.lookup(product['title'])
            except Exception as e:
                stats.warn(f"HLTB for {product['title']!r}: {e}")
        rows.append(_build_row(gog_id, product, price_doc, hltb_data))
        stats.ok += 1
    payload = {'fetched_at': datetime.now(UTC).isoformat(), 'store': 'wishlist_gog', 'game_count': len(rows), 'games': sorted(rows, key=lambda g: (g.get('name') or '').lower())}
    write_catalog_text(GAMES_WISHLIST_GOG_JSON, json.dumps(payload, indent=2, ensure_ascii=False))
    print(f'\nWrote {len(rows)} games to {GAMES_WISHLIST_GOG_JSON}.', flush=True)
    return stats.finish('fetch_gog_wishlist', t0, exit_code=0, extra=f'{len(rows)} games')
if __name__ == '__main__':
    raise SystemExit(main())