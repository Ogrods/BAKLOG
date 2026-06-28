from __future__ import annotations
import re
import time
from typing import TYPE_CHECKING
from urllib.parse import unquote
from auth.cdp_browser import abort_if_browser_closed
from auth.cdp_compat import click_by_text
if TYPE_CHECKING:
    from auth.runner import AuthSession
POLL_SEC = 0.5
SUCCESS_WAIT_SEC = 300
MAX_STEAM_REGISTER_ATTEMPTS = 5
KEY_VALID = 'valid'
KEY_INVALID = 'invalid'
KEY_UNREACHABLE = 'unreachable'
STEAM_LOGIN_URL = 'https://steamcommunity.com/login/home/?goto=dev%2Fapikey'
STEAM_APIKEY_URL = 'https://steamcommunity.com/dev/apikey'
ITCH_KEYS_URL = 'https://itch.io/user/settings/api-keys'
ITCH_LOGIN_URL = 'https://itch.io/login'
ITAD_APPS_URL = 'https://isthereanydeal.com/apps/my/'
XBL_DASHBOARD_URL = 'https://xbl.io/dashboard'
_STEAM_KEY_RE = re.compile('\\b([0-9A-F]{32})\\b', re.I)
_STEAM_ID_RE = re.compile('\\b(7656119\\d{10})\\b')
_ITCH_KEY_RE = re.compile('\\b([a-zA-Z0-9]{20,64})\\b')
_ITAD_KEY_RE = re.compile('\\b([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\\b', re.I)
_XBL_KEY_RE = re.compile('\\b([a-zA-Z0-9]{24,128})\\b')

def _steam_id_from_cookies(context) -> str:
    try:
        for cookie in context.cookies() or []:
            if cookie.get('name') != 'steamLoginSecure':
                continue
            value = unquote(str(cookie.get('value', '')))
            m = _STEAM_ID_RE.search(value)
            if m:
                return m.group(1)
    except Exception:
        pass
    return ''

def _steam_steam_id(page, context=None) -> str:
    if context is not None:
        sid = _steam_id_from_cookies(context)
        if sid:
            return sid
    try:
        sid = page.evaluate('() => {\n                if (typeof g_steamID !== \'undefined\' && g_steamID) return String(g_steamID);\n                const el = document.querySelector(\'[data-steamid]\');\n                if (el) return el.getAttribute(\'data-steamid\') || \'\';\n                const m = document.documentElement.innerHTML.match(/g_steamID\\s*=\\s*"(\\d+)"/);\n                return m ? m[1] : \'\';\n            }')
        if isinstance(sid, str) and _STEAM_ID_RE.fullmatch(sid.strip()):
            return sid.strip()
    except Exception:
        pass
    return ''

def _steam_tick_agreement(page) -> None:
    try:
        page.evaluate('() => {\n                const boxes = Array.from(document.querySelectorAll(\'input[type="checkbox"]\'));\n                const tick = cb => {\n                    if (cb && !cb.checked) {\n                        cb.checked = true;\n                        cb.dispatchEvent(new Event(\'input\', { bubbles: true }));\n                        cb.dispatchEvent(new Event(\'change\', { bubbles: true }));\n                    }\n                };\n                let hit = false;\n                for (const cb of boxes) {\n                    const label = (cb.closest(\'label\') || {}).innerText || \'\';\n                    const ctx = ((cb.id || \'\') + \' \' + (cb.name || \'\') + \' \' + label).toLowerCase();\n                    if (ctx.includes(\'agree\') || ctx.includes(\'terms\')) {\n                        tick(cb);\n                        hit = true;\n                    }\n                }\n                if (!hit && boxes.length === 1) tick(boxes[0]);\n                return hit || boxes.length === 1;\n            }')
    except Exception:
        pass

def _steam_try_register_key(page) -> None:
    try:
        domain = page.locator('input[name="domain"], #domain, input[placeholder*="domain" i]').first
        if domain.count() == 0:
            return
        domain.fill('127.0.0.1', timeout=3000)
        _steam_tick_agreement(page)
        for label in ('Register', 'Request', 'Create'):
            btn = page.get_by_role('button', name=re.compile(label, re.I))
            if btn.count() > 0:
                btn.first.click(timeout=3000)
                page.wait_for_timeout(2500)
                return
        submit = page.locator('button[type="submit"], input[type="submit"]').first
        if submit.count() > 0:
            submit.click(timeout=3000)
            page.wait_for_timeout(2500)
    except Exception:
        pass

def _steam_registration_form_present(page) -> bool:
    try:
        domain = page.locator('input[name="domain"], #domain, input[placeholder*="domain" i]').first
        return domain.count() > 0
    except Exception:
        return False

def _steam_extract_from_page(page, context=None, *, try_register: bool=True) -> dict[str, str] | None:
    url = (page.url or '').lower()
    if 'login' in url and 'steamcommunity.com' in url:
        return None
    will_nav = 'steamcommunity.com' not in url or 'apikey' not in url
    if will_nav:
        try:
            page.goto(STEAM_APIKEY_URL, wait_until='domcontentloaded', timeout=20000)
        except Exception:
            return None
    if try_register:
        _steam_try_register_key(page)
    body = page.content()
    m = re.search('Key[:\\s#]*([0-9A-F]{32})', body, re.I)
    api_key = m.group(1) if m else ''
    if not api_key:
        keys = _STEAM_KEY_RE.findall(body)
        api_key = keys[0] if keys else ''
    steam_id = _steam_steam_id(page, context)
    if not api_key or not steam_id:
        return None
    return {'STEAM_API_KEY': api_key, 'STEAM_ID': steam_id}

def _validate_steam(creds: dict[str, str]) -> None:
    import requests
    key = creds['STEAM_API_KEY']
    sid = creds['STEAM_ID']
    resp = requests.get('https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/', params={'key': key, 'steamids': sid}, timeout=20)
    resp.raise_for_status()
    players = resp.json().get('response', {}).get('players') or []
    if not players:
        raise RuntimeError('Steam API key or SteamID64 is invalid — check sign-in and try again')

def extract_steam(page, context, session: AuthSession | None=None) -> dict[str, str]:
    deadline = time.time() + SUCCESS_WAIT_SEC
    register_attempts = 0
    saw_register_form = False
    last_message = 0.0
    while time.time() < deadline:
        abort_if_browser_closed(context)
        try:
            creds = _steam_extract_from_page(page, context, try_register=register_attempts < MAX_STEAM_REGISTER_ATTEMPTS)
        except Exception:
            creds = None
        if creds:
            _validate_steam(creds)
            return creds
        if _steam_registration_form_present(page):
            saw_register_form = True
            register_attempts += 1
        if session and time.time() - last_message > 5:
            last_message = time.time()
            session.emit('waiting_for_user', {'message': 'No Steam API key yet. Registering one for you with domain 127.0.0.1.' if saw_register_form else "Sign in to Steam and wait. We'll grab your API key automatically."})
        page.wait_for_timeout(int(POLL_SEC * 1000))
    if saw_register_form:
        raise RuntimeError("We couldn't auto-register a Steam Web API key. Open steamcommunity.com/dev/apikey, agree to the terms, register a key with domain 127.0.0.1, then click Connect again.")
    raise RuntimeError("We couldn't read your Steam API key. Make sure you're signed in to Steam, then click Connect again.")

def _scrape_keys_dom(page, *, pattern_hint: str='(?:API\\s*Key|apikey|access[_\\s-]?token)') -> list[str]:
    try:
        result = page.evaluate(f"""() => {{\n                const HINT = /{pattern_hint}/i;\n                const looks = s => typeof s === 'string'\n                    && /^[A-Za-z0-9_-]{{20,256}}$/.test(s)\n                    && !/^(localhost|undefined|null|true|false|en[-_]US|en|github)$/i.test(s);\n\n                // Reveal hidden keys — never click nav/external links\n                document.querySelectorAll('button, [role="button"]').forEach(el => {{\n                    if (el.tagName === 'A') return;\n                    if (el.hasAttribute('target')) return;\n                    const t = (el.innerText || '').trim().toLowerCase();\n                    if (/^(show|reveal|toggle)$/i.test(t)) {{\n                        try {{ el.click(); }} catch (e) {{}}\n                    }}\n                }});\n\n                const found = [];\n                for (const inp of document.querySelectorAll('input')) {{\n                    const v = inp.value || inp.getAttribute('value') || '';\n                    if (looks(v) && v.length >= 30) found.push(v);\n                }}\n                for (const el of document.querySelectorAll('code, pre, textarea, [data-clipboard-text]')) {{\n                    const v = (el.getAttribute && el.getAttribute('data-clipboard-text'))\n                        || el.innerText || el.textContent || '';\n                    const toks = v.match(/[A-Za-z0-9_-]{{30,256}}/g) || [];\n                    for (const t of toks) if (looks(t)) found.push(t);\n                }}\n                const body = document.body ? document.body.innerText : '';\n                let m;\n                const re = /([A-Za-z0-9_-]{{30,256}})/g;\n                // Strong hint context (within 60 chars after API Key label)\n                const idx = body.search(HINT);\n                if (idx >= 0) {{\n                    const slice = body.slice(idx, idx + 400);\n                    while ((m = re.exec(slice))) {{\n                        if (looks(m[1])) found.push(m[1]);\n                    }}\n                }}\n                return found;\n            }}""")
        if isinstance(result, list):
            return [str(x) for x in result if x]
    except Exception:
        pass
    return []

def validate_itch_key(key: str) -> str:
    import requests
    token = (key or '').strip()
    if not token:
        return KEY_INVALID
    try:
        resp = requests.get(f'https://itch.io/api/1/{token}/me', timeout=15)
    except requests.RequestException:
        return KEY_UNREACHABLE
    except Exception:
        return KEY_UNREACHABLE
    if resp.status_code == 200:
        return KEY_VALID
    if resp.status_code >= 500:
        return KEY_UNREACHABLE
    return KEY_INVALID

def _validate_itch(creds: dict[str, str]) -> bool:
    return validate_itch_key(creds.get('ITCH_API_KEY', '')) == KEY_VALID

def extract_itch(page, context, session: AuthSession | None=None) -> dict[str, str]:
    deadline = time.time() + SUCCESS_WAIT_SEC
    navigated = False
    generated = False
    last_message = 0.0
    while time.time() < deadline:
        abort_if_browser_closed(context)
        url = (page.url or '').lower()
        if any((p in url for p in ('/login', '/register', 'captcha', 'verify'))):
            if session and time.time() - last_message > 6:
                last_message = time.time()
                session.emit('waiting_for_user', {'message': "Sign in / verify on itch.io. We'll wait until you're done."})
            page.wait_for_timeout(1000)
            continue
        if 'itch.io' in url and '/user/settings/api-keys' not in url and (not navigated):
            try:
                page.goto(ITCH_KEYS_URL, wait_until='domcontentloaded', timeout=20000)
                navigated = True
                page.wait_for_timeout(1000)
            except Exception:
                page.wait_for_timeout(1000)
                continue
        if '/user/settings/api-keys' in (page.url or '').lower():
            candidates = _scrape_keys_dom(page, pattern_hint='API\\s*Key|api[_\\s-]?key|key')
            for token in candidates:
                if '/' in token or token.endswith('='):
                    continue
                if _validate_itch({'ITCH_API_KEY': token}):
                    return {'ITCH_API_KEY': token}
            if not generated:
                try:
                    if click_by_text(page, ('generate new api key', 'generate'), tags=('button', 'a', "input[type='submit']")):
                        generated = True
                        page.wait_for_timeout(1500)
                except Exception:
                    pass
        if session and time.time() - last_message > 6:
            last_message = time.time()
            session.emit('waiting_for_user', {'message': "Sign in to itch.io. Once the API Keys page loads we'll save your key."})
        page.wait_for_timeout(int(POLL_SEC * 1000))
    raise RuntimeError('Could not capture an itch.io API key — sign in fully, then try Connect again.')

def _itad_register_app(page) -> None:
    try:
        for label in ('Register', 'New app', 'Create'):
            if click_by_text(page, (label.lower(),)):
                page.wait_for_timeout(1000)
                break
        for sel in ('input[name="title"]', 'input[name="name"]', 'input[type="text"]'):
            inp = page.locator(sel).first
            if inp.count() > 0:
                inp.fill('Steam Backlog', timeout=2500)
                break
        for label in ('Register', 'Create', 'Save'):
            if click_by_text(page, (label.lower(),), tags=('button', "input[type='submit']")):
                page.wait_for_timeout(2500)
                break
    except Exception:
        pass

def validate_itad_key(key: str) -> str:
    import requests
    token = (key or '').strip()
    if not token:
        return KEY_INVALID
    try:
        resp = requests.get('https://api.isthereanydeal.com/games/lookup/v1', params={'key': token, 'title': 'Portal'}, timeout=15)
    except requests.RequestException:
        return KEY_UNREACHABLE
    except Exception:
        return KEY_UNREACHABLE
    if resp.status_code == 200:
        return KEY_VALID
    if resp.status_code >= 500:
        return KEY_UNREACHABLE
    return KEY_INVALID

def _validate_itad(creds: dict[str, str]) -> bool:
    return validate_itad_key(creds.get('ITAD_API_KEY', '')) == KEY_VALID

def _scrape_itad_uuids(page) -> list[str]:
    try:
        result = page.evaluate('() => {\n                document.querySelectorAll(\'button, [role="button"]\').forEach(el => {\n                    if (el.tagName === \'A\') return;\n                    if (el.hasAttribute(\'target\')) return;\n                    const t = (el.innerText || \'\').trim().toLowerCase();\n                    if (/^(show|reveal|toggle)$/i.test(t)) {\n                        try { el.click(); } catch (e) {}\n                    }\n                });\n                const out = new Set();\n                const RE = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi;\n                document.querySelectorAll(\'input\').forEach(inp => {\n                    const v = inp.value || inp.getAttribute(\'value\') || \'\';\n                    const m = v.match(RE);\n                    if (m) m.forEach(x => out.add(x));\n                });\n                document.querySelectorAll(\'code, pre, textarea, [data-clipboard-text]\').forEach(el => {\n                    const v = (el.getAttribute && el.getAttribute(\'data-clipboard-text\'))\n                        || el.innerText || el.textContent || \'\';\n                    const m = v.match(RE);\n                    if (m) m.forEach(x => out.add(x));\n                });\n                const body = document.body ? document.body.innerText : \'\';\n                const m = body.match(RE);\n                if (m) m.forEach(x => out.add(x));\n                return Array.from(out);\n            }')
        if isinstance(result, list):
            return [str(x) for x in result]
    except Exception:
        pass
    return []

def extract_itad(page, context, session: AuthSession | None=None) -> dict[str, str]:
    deadline = time.time() + SUCCESS_WAIT_SEC
    navigated = False
    registered = False
    expanded_apps = False
    last_message = 0.0
    while time.time() < deadline:
        abort_if_browser_closed(context)
        url = (page.url or '').lower()
        if any((p in url for p in ('oauth/login', 'auth/login', 'captcha', 'verify'))):
            if session and time.time() - last_message > 6:
                last_message = time.time()
                session.emit('waiting_for_user', {'message': "Sign in to IsThereAnyDeal. We'll wait until you're done."})
            page.wait_for_timeout(1000)
            continue
        if 'isthereanydeal.com' in url and '/apps/' not in url and (not navigated):
            try:
                page.goto(ITAD_APPS_URL, wait_until='domcontentloaded', timeout=20000)
                navigated = True
                page.wait_for_timeout(1000)
            except Exception:
                page.wait_for_timeout(1000)
                continue
        if 'isthereanydeal.com/apps' in (page.url or '').lower():
            for uuid in _scrape_itad_uuids(page):
                if _validate_itad({'ITAD_API_KEY': uuid}):
                    return {'ITAD_API_KEY': uuid}
            if not expanded_apps:
                try:
                    links = page.locator('a[href*="/apps/"]:not([href$="/apps/"]):not([href$="/apps/my/"])')
                    count = min(links.count(), 5)
                    for i in range(count):
                        try:
                            links.nth(i).click(timeout=3000)
                            page.wait_for_timeout(1500)
                            for uuid in _scrape_itad_uuids(page):
                                if _validate_itad({'ITAD_API_KEY': uuid}):
                                    return {'ITAD_API_KEY': uuid}
                            page.go_back(wait_until='domcontentloaded', timeout=10000)
                            page.wait_for_timeout(800)
                        except Exception:
                            try:
                                page.goto(ITAD_APPS_URL, wait_until='domcontentloaded', timeout=15000)
                            except Exception:
                                pass
                except Exception:
                    pass
                expanded_apps = True
            if not registered:
                _itad_register_app(page)
                registered = True
                page.wait_for_timeout(2000)
                for uuid in _scrape_itad_uuids(page):
                    if _validate_itad({'ITAD_API_KEY': uuid}):
                        return {'ITAD_API_KEY': uuid}
        if session and time.time() - last_message > 6:
            last_message = time.time()
            session.emit('waiting_for_user', {'message': "Sign in to IsThereAnyDeal. We'll open your app's key page automatically."})
        page.wait_for_timeout(int(POLL_SEC * 1000))
    raise RuntimeError('Could not capture an IsThereAnyDeal API key. Make sure you have at least one app registered at isthereanydeal.com/apps/my/, then click Connect again.')

def _xbl_signed_in(url: str) -> bool:
    u = (url or '').lower()
    if 'xbl.io' not in u:
        return False
    if any((p in u for p in ('/login', 'login.live.com', 'account.microsoft.com'))):
        return False
    return True

def _xbl_fetch_keys_json(page) -> list[str]:
    try:
        result = page.evaluate("async () => {\n                const urls = ['https://xbl.io/keys', 'https://xbl.io/app/keys'];\n                const out = [];\n                const seen = new Set();\n                const push = v => {\n                    if (typeof v !== 'string') return;\n                    v = v.trim();\n                    if (!v || seen.has(v)) return;\n                    if (!/^[A-Za-z0-9_-]{24,128}$/.test(v)) return;\n                    seen.add(v);\n                    out.push(v);\n                };\n                for (const u of urls) {\n                    try {\n                        const res = await fetch(u, {\n                            credentials: 'include',\n                            headers: { Accept: 'application/json' },\n                        });\n                        if (!res.ok) continue;\n                        const data = await res.json();\n                        const keys = (data && data.keys) || [];\n                        for (const k of keys) {\n                            if (!k) continue;\n                            push(k.key || k.apiKey || k.value || '');\n                        }\n                        if (out.length) return out;\n                    } catch (e) {}\n                }\n                return out;\n            }")
        if isinstance(result, list):
            return [str(x).strip() for x in result if isinstance(x, str) and x.strip()]
    except Exception:
        pass
    return []

def _xbl_scrape_key_candidates(page) -> list[str]:
    try:
        result = page.evaluate('() => {\n                const out = [];\n                const seen = new Set();\n                const push = s => {\n                    if (typeof s !== \'string\') return;\n                    s = s.trim();\n                    if (!/^[A-Za-z0-9_-]{24,128}$/.test(s)) return;\n                    if (/^(localhost|undefined|null|true|false)$/i.test(s)) return;\n                    if (seen.has(s)) return;\n                    seen.add(s);\n                    out.push(s);\n                };\n\n                // Reveal hidden keys — only safe clicks (no nav, no targets)\n                document.querySelectorAll(\'button, [role="button"]\').forEach(el => {\n                    const t = (el.innerText || \'\').trim().toLowerCase();\n                    if (el.tagName === \'A\') return;\n                    if (el.hasAttribute(\'target\')) return;\n                    if (/^(show|reveal|toggle)$/i.test(t)) {\n                        try { el.click(); } catch (e) {}\n                    }\n                });\n\n                // 1. Highest confidence: token right after an "API key" label\n                //    (xbl.io labels the key "authorizationCode" / "Authorization")\n                const body = document.body ? document.body.innerText : \'\';\n                const labelled = body.match(\n                    /(?:authorizationCode|authorization|API\\s*Key|X-Authorization|apikey)[^A-Za-z0-9]+([A-Za-z0-9_-]{24,128})/ig\n                ) || [];\n                for (const chunk of labelled) {\n                    const m = chunk.match(/([A-Za-z0-9_-]{24,128})\\s*$/);\n                    if (m) push(m[1]);\n                }\n                // 2. data-clipboard-text (copy buttons usually carry the raw key)\n                for (const el of document.querySelectorAll(\'[data-clipboard-text]\')) {\n                    push(el.getAttribute(\'data-clipboard-text\') || \'\');\n                }\n                // 3. Input field values (readonly key fields)\n                for (const inp of document.querySelectorAll(\'input\')) {\n                    push(inp.value || inp.getAttribute(\'value\') || \'\');\n                }\n                // 4. Code/pre/textarea blocks\n                for (const el of document.querySelectorAll(\'code, pre, textarea\')) {\n                    const v = el.innerText || el.textContent || \'\';\n                    const toks = v.match(/[A-Za-z0-9_-]{24,128}/g) || [];\n                    toks.forEach(push);\n                }\n                // 5. Bare body tokens (last resort)\n                const bare = body.match(/[A-Za-z0-9_-]{24,128}/g) || [];\n                bare.forEach(push);\n\n                return out.slice(0, 8);\n            }')
        if isinstance(result, list):
            return [s.strip() for s in result if isinstance(s, str) and s.strip()]
    except Exception:
        pass
    return []

def _xbox_key_check(key: str) -> str:
    from clients.xbox_client import XboxAuthError, XboxClient, XboxRateLimitError
    try:
        XboxClient(key).get_account()
        return 'valid'
    except XboxRateLimitError:
        return 'rate_limited'
    except XboxAuthError:
        return 'invalid'
    except Exception:
        return 'invalid'

def _xbox_key_valid(key: str) -> bool:
    return _xbox_key_check(key) == 'valid'

def extract_xbox(page, context, session: AuthSession | None=None) -> dict[str, str]:
    captured: dict[str, str] = {}
    header_key: dict[str, str] = {}

    def on_request(request) -> None:
        if 'xbl.io' not in (request.url or '').lower():
            return
        for h in ('x-authorization', 'X-Authorization'):
            value = request.headers.get(h)
            if value and len(value) >= 24:
                header_key['XBL_API_KEY'] = value.strip()
                return
    page.on('request', on_request)
    deadline = time.time() + SUCCESS_WAIT_SEC
    last_message = 0.0

    def _accept(candidates: list[str]) -> dict[str, str] | None:
        for cand in candidates:
            if _xbox_key_valid(cand):
                captured['XBL_API_KEY'] = cand
                return captured
        return None

    def _accept_trusted(candidates: list[str]) -> dict[str, str] | None:
        for cand in candidates:
            if _xbox_key_check(cand) in ('valid', 'rate_limited'):
                captured['XBL_API_KEY'] = cand
                return captured
        return None
    while time.time() < deadline:
        abort_if_browser_closed(context)
        if header_key.get('XBL_API_KEY'):
            hit = _accept_trusted([header_key['XBL_API_KEY']])
            if hit:
                return hit
        url = (page.url or '').lower()
        if _xbl_signed_in(url):
            hit = _accept_trusted(_xbl_fetch_keys_json(page))
            if hit:
                return hit
            hit = _accept(_xbl_scrape_key_candidates(page))
            if hit:
                return hit
        if session and time.time() - last_message > 6:
            last_message = time.time()
            session.emit('waiting_for_user', {'message': "Signed in to OpenXBL? If you don't see your API key on the dashboard, you may need to verify your phone/email first on xbl.io." if _xbl_signed_in(url) else "Click “Sign in with Xbox Live” on the xbl.io page to get your API key — we'll capture it automatically."})
        page.wait_for_timeout(int(POLL_SEC * 1000))
    raise RuntimeError('Could not find an OpenXBL API key. Sign in at xbl.io, complete any phone/email verification, then click Connect again.')