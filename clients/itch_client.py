from __future__ import annotations
import json
import time
from pathlib import Path
import requests
from fetchers._progress import HeartbeatTimer, heartbeat, progress_line
BASE_URL = 'https://itch.io/api/1'
DEFAULT_PAGE_SIZE_FALLBACK = 50
REQUEST_DELAY_SEC = 0.4

class ItchAuthError(Exception):

class ItchApiError(Exception):

def _default_itch_cache_dir() -> Path:
    from shared.profile_paths import profile_cache_dir
    return profile_cache_dir() / 'itch'

class ItchClient:

    def __init__(self, api_key: str, cache_dir: Path | None=None, timeout: int=30) -> None:
        if cache_dir is None:
            cache_dir = _default_itch_cache_dir()
        if not api_key:
            raise ItchAuthError('Set ITCH_API_KEY in .env (https://itch.io/user/settings/api-keys)')
        self.api_key = api_key.strip()
        self.cache_dir = cache_dir
        (self.cache_dir / 'games').mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self._last_call = 0.0
        self.session = requests.Session()
        self.session.headers['User-Agent'] = 'steam-backlog/1.0 (+itch)'

    def _throttle(self) -> None:
        elapsed = time.time() - self._last_call
        if elapsed < REQUEST_DELAY_SEC:
            time.sleep(REQUEST_DELAY_SEC - elapsed)
        self._last_call = time.time()

    def _get(self, path: str, params: dict | None=None) -> dict:
        self._throttle()
        url = f'{BASE_URL}/{self.api_key}/{path}'
        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
        except requests.RequestException as e:
            raise ItchApiError(f'itch.io request failed: {e}') from e
        if resp.status_code in (401, 403):
            raise ItchAuthError('itch.io rejected the API key (401/403). Regenerate at https://itch.io/user/settings/api-keys')
        if resp.status_code >= 400:
            raise ItchApiError(f'itch.io HTTP {resp.status_code}: {resp.text[:200]}')
        try:
            data = resp.json()
        except ValueError as e:
            raise ItchApiError(f'itch.io returned non-JSON: {e}') from e
        if isinstance(data, dict) and data.get('errors'):
            raise ItchApiError(f"itch.io error: {data['errors']}")
        return data

    def me(self) -> dict:
        return self._get('me').get('user', {})

    def owned_keys_page(self, page: int) -> list[dict]:
        data = self._get('my-owned-keys', {'page': page})
        keys = data.get('owned_keys') or data.get('download_keys') or []
        if not isinstance(keys, list):
            return []
        return keys

    def all_owned_keys(self) -> list[dict]:
        hb = HeartbeatTimer(interval=25.0)
        out: list[dict] = []
        seen_ids: set[int] = set()
        page = 1
        while True:
            hb.tick_progress(page, 0, 'itch owned-keys', f'{len(out)} games')
            chunk = self.owned_keys_page(page)
            if not chunk:
                break
            new_in_page = 0
            for entry in chunk:
                game = entry.get('game') or {}
                gid = game.get('id')
                if gid is None or gid in seen_ids:
                    continue
                seen_ids.add(gid)
                out.append(entry)
                new_in_page += 1
            if new_in_page == 0:
                break
            heartbeat(progress_line(page, 0, 'itch owned-keys', f'{len(out)} games'))
            page += 1
            if page > 200:
                break
        return out

    def game(self, game_id: int) -> dict:
        cache_path = self.cache_dir / 'games' / f'{game_id}.json'
        if cache_path.exists():
            try:
                return json.loads(cache_path.read_text(encoding='utf-8'))
            except (OSError, json.JSONDecodeError):
                pass
        data = self._get(f'game/{game_id}')
        cache_path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        return data
__all__ = ['ItchClient', 'ItchAuthError', 'ItchApiError']