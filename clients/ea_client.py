from __future__ import annotations
import json
import time
from urllib.parse import quote
import requests
GRAPHQL_URL = 'https://service-aggregation-layer.juno.ea.com/graphql'
EA_WEB_ORIGIN = 'https://www.ea.com'
EA_WEB_REFERER = 'https://www.ea.com/sales/deals'
OWNED_GAMES_HASH = '5de4178ee7e1f084ce9deca856c74a9e03547a67dfafc0cb844d532fb54ae73d'
PLAY_TIMES_HASH = '3f09b35e06b75c74d8ec3e520a598ebb5e2992b1e1268b6dd3b8ed99b9fafb29'
USER_SUBSCRIPTION_HASH = 'd127c63383688258dd6133009a12668a2f3d1a6d47c4927d00fa84a398205a88'
PLAY_TIMES_QUERY = '\nquery GetGamePlayTimes($gameSlugs: [String!]!) {\n  me {\n    recentGames(gameSlugs: $gameSlugs) {\n      items {\n        gameSlug\n        totalPlayTimeSeconds\n        lastSessionEndDate\n      }\n    }\n  }\n}\n'
REAL_OWNERSHIP = frozenset({'UNKNOWN', 'ASSOCIATION', 'PURCHASE', 'REDEMPTION', 'GIFT_RECEIPT', 'ENTITLEMENT_GRANT', 'DIRECT_ENTITLEMENT', 'PRE_ORDER_PURCHASE', 'STEAM', 'EPIC'})
EA_PLAY_OWNERSHIP = frozenset({'VAULT', 'STEAM_VAULT', 'STEAM_SUBSCRIPTION', 'EPIC_VAULT', 'EPIC_SUBSCRIPTION'})
XGP_ONLY = frozenset({'XGP_VAULT'})
OWNED_GAMES_QUERY = '\nquery getPreloadedOwnedGames(\n  $limit: Int!\n  $next: String!\n) {\n  me {\n    ownedGameProducts(\n      locale: "DEFAULT"\n      paging: { limit: $limit, next: $next }\n      type: [DIGITAL_FULL_GAME, PACKAGED_FULL_GAME]\n      entitlementEnabled: true\n      storefronts: [EA]\n      ownershipMethod: [PURCHASE, REDEMPTION, ENTITLEMENT_GRANT]\n      platforms: [PC]\n    ) {\n      next\n      items {\n        originOfferId\n        product {\n          name\n          gameSlug\n        }\n      }\n    }\n  }\n}\n'
_REQUEST_DELAY_SEC = 0.15
REQUEST_DELAY_SEC = _REQUEST_DELAY_SEC
_OWNED_VARIABLES_BASE = {'isMac': False, 'locale': 'DEFAULT', 'type': ['DIGITAL_FULL_GAME', 'PACKAGED_FULL_GAME'], 'entitlementEnabled': True, 'storefronts': ['EA'], 'ownershipMethods': sorted(REAL_OWNERSHIP | EA_PLAY_OWNERSHIP | XGP_ONLY), 'platforms': ['PC']}

class EaAuthError(Exception):
    pass

class EaCaptureError(Exception):

def _persisted_url(operation: str, variables: dict, sha256_hash: str) -> str:
    variables_json = json.dumps(variables, separators=(',', ':'))
    ext = json.dumps({'persistedQuery': {'version': 1, 'sha256Hash': sha256_hash}}, separators=(',', ':'))
    return f'{GRAPHQL_URL}?operationName={quote(operation)}&variables={quote(variables_json)}&extensions={quote(ext)}'

def _apply_cookies(session: requests.Session, cookies: list[dict] | dict | None) -> None:
    if isinstance(cookies, dict):
        for name, value in cookies.items():
            if name and value is not None:
                session.cookies.set(name, value, domain='.ea.com', path='/')
        return
    for c in cookies or []:
        name = c.get('name')
        value = c.get('value')
        if not name or value is None:
            continue
        session.cookies.set(name, value, domain=(c.get('domain') or '.ea.com').lstrip('.'), path=c.get('path') or '/')

def owned_games_full_document_body(*, limit: int, offset: str='0', preload: bool=True) -> dict:
    _ = preload
    return {'operationName': 'getPreloadedOwnedGames', 'query': OWNED_GAMES_QUERY, 'variables': {'limit': limit, 'next': offset}}

class EaClient:

    def __init__(self, access_token: str='', cookies: list[dict] | dict | None=None) -> None:
        token = (access_token or '').strip()
        if token.lower().startswith('bearer '):
            token = token[7:].strip()
        has_cookies = bool(cookies)
        if not token and (not has_cookies):
            raise EaAuthError('No EA web session — connect EA App on the Connections page first.')
        self._access_token = token
        self._cookie_mode = not token
        self._last_request = 0.0
        self.session = requests.Session()
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36', 'Accept': 'application/json'}
        if self._cookie_mode or token:
            headers.update({'Origin': EA_WEB_ORIGIN, 'Referer': EA_WEB_REFERER, 'x-client-id': 'eacom-fe'})
        if token:
            headers['Authorization'] = f'Bearer {token}'
        self.session.headers.update(headers)
        _apply_cookies(self.session, cookies)

    def _throttle(self) -> None:
        elapsed = time.time() - self._last_request
        if elapsed < REQUEST_DELAY_SEC:
            time.sleep(REQUEST_DELAY_SEC - elapsed)
        self._last_request = time.time()

    def _raise_graphql_errors(self, data: dict, resp: requests.Response) -> None:
        if resp.status_code in (401, 403):
            raise EaAuthError(f'EA GraphQL unauthorized ({resp.status_code}) — reconnect EA App.')
        if resp.status_code >= 400:
            raise EaAuthError(f'EA GraphQL HTTP {resp.status_code}: {resp.text[:300]}')
        if data.get('errors'):
            err = data['errors'][0] if data['errors'] else {}
            code = ((err.get('extensions') or {}).get('code') or '').upper()
            msg = str(err.get('message') or '')
            if code == 'UNAUTHENTICATED' or 'not authenticated' in msg.lower():
                raise EaAuthError('EA GraphQL not authenticated — reconnect EA App.')
            raise EaAuthError(f"EA GraphQL errors: {data['errors'][:1]}")

    def _graphql_get(self, operation: str, variables: dict, sha256_hash: str) -> dict:
        self._throttle()
        url = _persisted_url(operation, variables, sha256_hash)
        resp = self.session.get(url, timeout=60)
        data = resp.json()
        self._raise_graphql_errors(data, resp)
        return data

    def _graphql_post(self, operation: str, query: str, variables: dict) -> dict:
        self._throttle()
        resp = self.session.post(GRAPHQL_URL, json={'operationName': operation, 'query': query, 'variables': variables}, timeout=60)
        data = resp.json()
        self._raise_graphql_errors(data, resp)
        return data

    def _graphql_apq_post(self, operation: str, variables: dict, sha256_hash: str) -> dict:
        self._throttle()
        resp = self.session.post(GRAPHQL_URL, json={'operationName': operation, 'variables': variables, 'extensions': {'persistedQuery': {'version': 1, 'sha256Hash': sha256_hash}}}, timeout=60)
        data = resp.json()
        self._raise_graphql_errors(data, resp)
        return data

    def probe_user_subscription(self) -> None:
        root = self._graphql_apq_post('GetUserSubscription', {}, USER_SUBSCRIPTION_HASH)
        if (root.get('data') or {}).get('me') is None:
            raise EaAuthError('EA GraphQL not authenticated — reconnect EA App.')

    def probe_owned_games(self) -> None:
        if self._cookie_mode:
            self.probe_user_subscription()
            return
        self._graphql_get('getPreloadedOwnedGames', {**_OWNED_VARIABLES_BASE, 'addFieldsToPreloadGames': False, 'limit': 1, 'next': '0'}, OWNED_GAMES_HASH)

    def _owned_page_variables(self, *, limit: int, offset: str, preload: bool) -> dict:
        return {**_OWNED_VARIABLES_BASE, 'addFieldsToPreloadGames': preload, 'limit': limit, 'next': offset}

    def _owned_items_from_root(self, root: dict) -> tuple[list[dict], str | None]:
        owned = (root.get('data') or {}).get('me', {}).get('ownedGameProducts') or {}
        items = owned.get('items') or []
        batch = [i for i in items if isinstance(i, dict)]
        nxt = owned.get('next')
        return (batch, str(nxt) if nxt else None)

    def _owned_full_page_variables(self, *, limit: int, offset: str, preload: bool) -> dict:
        _ = preload
        return {'limit': limit, 'next': offset}

    def _get_owned_games_full(self) -> list[dict]:
        out: list[dict] = []
        offset = '0'
        while True:
            root = self._graphql_post('getPreloadedOwnedGames', OWNED_GAMES_QUERY, self._owned_full_page_variables(limit=500, offset=offset, preload=True))
            batch, offset = self._owned_items_from_root(root)
            out.extend(batch)
            if not offset:
                break
        return out

    def _get_owned_games_apq(self) -> list[dict]:
        out: list[dict] = []
        offset = '0'
        while True:
            variables = self._owned_page_variables(limit=500, offset=offset, preload=True)
            if self._cookie_mode:
                root = self._graphql_apq_post('getPreloadedOwnedGames', variables, OWNED_GAMES_HASH)
            else:
                root = self._graphql_get('getPreloadedOwnedGames', variables, OWNED_GAMES_HASH)
            owned = (root.get('data') or {}).get('me', {}).get('ownedGameProducts') or {}
            items = owned.get('items') or []
            if isinstance(items, list):
                out.extend((i for i in items if isinstance(i, dict)))
            offset = owned.get('next')
            if not offset:
                break
        return out

    @staticmethod
    def _should_fallback_owned_document(exc: EaAuthError) -> bool:
        msg = str(exc)
        return 'PersistedQueryNotFound' in msg or 'Graphql validation error' in msg

    def get_owned_games(self) -> list[dict]:
        try:
            return self._get_owned_games_apq()
        except EaAuthError as exc:
            if not self._should_fallback_owned_document(exc):
                raise
            items = self._get_owned_games_full()
            return items

    def get_play_times(self, slugs: list[str]) -> list[dict]:
        if not slugs:
            return []
        if self._cookie_mode:
            root = self._graphql_post('GetGamePlayTimes', PLAY_TIMES_QUERY, {'gameSlugs': slugs})
        else:
            root = self._graphql_get('GetGamePlayTimes', {'gameSlugs': slugs}, PLAY_TIMES_HASH)
        recent = (root.get('data') or {}).get('me', {}).get('recentGames') or {}
        items = recent.get('items') or []
        return [i for i in items if isinstance(i, dict)]