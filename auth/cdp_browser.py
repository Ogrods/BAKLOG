from __future__ import annotations
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import requests
try:
    import websocket
except ImportError as exc:
    raise RuntimeError('websocket-client is required for browser sign-in. Run: pip install websocket-client') from exc

def _subprocess_no_window_flags() -> int:
    if os.name != 'nt':
        return 0
    return getattr(subprocess, 'CREATE_NO_WINDOW', 0)

def _pids_listening_on_local_port(port: int) -> list[int]:
    if port <= 0:
        return []
    pids: set[int] = set()
    if os.name == 'nt':
        try:
            out = subprocess.check_output(['netstat', '-ano'], text=True, encoding='utf-8', errors='ignore', creationflags=_subprocess_no_window_flags())
        except Exception:
            return []
        needle = f':{port}'
        for line in out.splitlines():
            if 'LISTENING' not in line.upper() or needle not in line:
                continue
            parts = line.split()
            if not parts:
                continue
            try:
                pids.add(int(parts[-1]))
            except ValueError:
                pass
    else:
        try:
            out = subprocess.check_output(['lsof', '-i', f':{port}', '-sTCP:LISTEN', '-t'], text=True, errors='ignore', timeout=5)
            for line in out.splitlines():
                try:
                    pids.add(int(line.strip()))
                except ValueError:
                    pass
        except Exception:
            pass
    return sorted(pids)

def _kill_pids(pids: list[int]) -> list[int]:
    killed: list[int] = []
    flags = _subprocess_no_window_flags()
    for pid in pids:
        if pid <= 0:
            continue
        try:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags, check=False)
            else:
                import signal
                os.kill(pid, signal.SIGTERM)
            killed.append(pid)
        except Exception:
            pass
    return killed
_CHROMIUM_EXE_NAMES = frozenset({'chrome.exe', 'msedge.exe', 'msedgewebview2.exe'})

def _profile_dir_needles(profile: Path) -> tuple[str, ...]:
    resolved = profile.resolve()
    raw = str(resolved)
    return tuple({raw.lower(), raw.replace('\\', '/').lower()})

def _clear_stale_chromium_profile_lock_files(profile: Path) -> bool:
    removed = False
    for name in ('SingletonLock', 'SingletonSocket', 'SingletonCookie', 'lockfile', 'LOCK'):
        path = profile / name
        if not path.exists():
            continue
        try:
            path.unlink()
            removed = True
        except OSError:
            pass
    return removed

def pids_holding_chromium_profile(user_data_dir: str | Path) -> list[int]:
    needles = _profile_dir_needles(Path(user_data_dir))
    if not needles:
        return []
    pids: set[int] = set()
    flags = _subprocess_no_window_flags()
    if os.name == 'nt':
        ps_cmd = "Get-CimInstance Win32_Process | Where-Object { $_.Name -in @('chrome.exe','msedge.exe','msedgewebview2.exe') } | ForEach-Object { $_.ProcessId.ToString() + '|' + ([string]$_.CommandLine) }"
        try:
            out = subprocess.check_output(['powershell', '-NoProfile', '-Command', ps_cmd], text=True, encoding='utf-8', errors='ignore', creationflags=flags, timeout=12)
        except Exception:
            try:
                out = subprocess.check_output(['wmic', 'process', 'where', "name='chrome.exe' or name='msedge.exe'", 'get', 'ProcessId,CommandLine', '/format:csv'], text=True, encoding='utf-8', errors='ignore', creationflags=flags, timeout=12)
            except Exception:
                return []
            for line in out.splitlines():
                if not line.strip() or line.lower().startswith('node,'):
                    continue
                parts = line.split(',', 2)
                if len(parts) < 3:
                    continue
                try:
                    pid_s = parts[1].strip()
                    cmd = parts[2]
                except IndexError:
                    continue
                cmd_l = cmd.lower()
                if not any((needle in cmd_l and '--user-data-dir' in cmd_l for needle in needles)):
                    continue
                try:
                    pids.add(int(pid_s))
                except ValueError:
                    pass
            return sorted(pids)
        for line in out.splitlines():
            if '|' not in line:
                continue
            pid_s, cmd = line.split('|', 1)
            cmd_l = cmd.lower()
            if not any((needle in cmd_l and '--user-data-dir' in cmd_l for needle in needles)):
                continue
            try:
                pids.add(int(pid_s.strip()))
            except ValueError:
                pass
        return sorted(pids)
    try:
        out = subprocess.check_output(['ps', '-ax', '-o', 'pid=,command='], text=True, errors='ignore', timeout=8)
    except Exception:
        return []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        pid_s, cmd = (parts[0], parts[1])
        cmd_l = cmd.lower()
        exe = Path(cmd.split()[0]).name.lower() if cmd.split() else ''
        if exe not in _CHROMIUM_EXE_NAMES:
            continue
        if not any((needle in cmd_l and '--user-data-dir' in cmd_l for needle in needles)):
            continue
        try:
            pids.add(int(pid_s))
        except ValueError:
            pass
    return sorted(pids)

def release_chromium_profile_lock(user_data_dir: str | Path) -> list[int]:
    profile = Path(user_data_dir)
    pids = pids_holding_chromium_profile(profile)
    if pids:
        _kill_pids(pids)
        time.sleep(0.35)
    else:
        _clear_stale_chromium_profile_lock_files(profile)
    return pids
_BLANK_URLS = frozenset({'', 'about:blank', 'chrome://newtab/'})
_AUTOMATION_MASK_SCRIPT = "try {  Object.defineProperty(navigator, 'webdriver', {get: () => undefined});} catch (e) {}try { delete Navigator.prototype.webdriver; } catch (e) {}"
STEALTH_INIT_SCRIPT = "\n(() => {\n  try { Object.defineProperty(navigator, 'webdriver', { get: () => undefined, configurable: true }); } catch (e) {}\n  try {\n    const orig = Object.getOwnPropertyDescriptor(Navigator.prototype, 'webdriver');\n    if (orig) Object.defineProperty(Navigator.prototype, 'webdriver', { get: () => undefined });\n  } catch (e) {}\n  try {\n    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'], configurable: true });\n    Object.defineProperty(navigator, 'plugins', {\n      get: () => [\n        { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },\n        { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },\n        { name: 'Native Client', filename: 'internal-nacl-plugin' },\n      ],\n      configurable: true,\n    });\n  } catch (e) {}\n  try { window.chrome = window.chrome || { runtime: {}, app: { isInstalled: false } }; } catch (e) {}\n  try {\n    const oq = window.navigator.permissions && window.navigator.permissions.query;\n    if (oq) {\n      window.navigator.permissions.query = (p) =>\n        p && p.name === 'notifications'\n          ? Promise.resolve({ state: Notification.permission })\n          : oq.call(window.navigator.permissions, p);\n    }\n  } catch (e) {}\n  try { Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 }); } catch (e) {}\n  try { Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 }); } catch (e) {}\n  try { Object.defineProperty(navigator, 'maxTouchPoints', { get: () => 0 }); } catch (e) {}\n  try { delete Object.getPrototypeOf(navigator).webdriver; } catch (e) {}\n})();\n"
_BROWSER_LAUNCH_HINT = 'Install Google Chrome or Microsoft Edge, set BAKLOG_CHROME_PATH to the browser executable, or try the other installed browser.'

def auth_banner_init_script(message: str) -> str:
    default = json.dumps(message)
    style = 'position:fixed;left:50%;bottom:18px;transform:translateX(-50%);z-index:2147483647;max-width:min(680px,92vw);box-sizing:border-box;padding:11px 18px;border-radius:10px;background:linear-gradient(90deg,#0f172a,#1e3a8a);color:#f8fafc;font:600 14px/1.45 system-ui,Segoe UI,Arial,sans-serif;text-align:center;box-shadow:0 6px 22px rgba(0,0,0,.45);border:1px solid rgba(148,163,184,.4);pointer-events:none;white-space:normal;'
    style_js = json.dumps(style)
    return f"(() => {{  try {{    if (window.top !== window) return;    const DEFAULT = {default};    const ID = '__baklog_auth_banner';    function ensure() {{      const root = document.documentElement; if (!root) return;      let bar = document.getElementById(ID);      if (!bar) {{        bar = document.createElement('div'); bar.id = ID;        bar.style.cssText = {style_js};        (document.body || root).appendChild(bar);      }}      bar.textContent = '\\uD83C\\uDFAE BAKLOG \\u2014 ' + (window.__baklogBannerMsg || DEFAULT);    }}    if (!window.__baklogBannerMsg) window.__baklogBannerMsg = DEFAULT;    window.__baklogSetBanner = function (m) {{ if (m) window.__baklogBannerMsg = String(m); ensure(); }};    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ensure);    else ensure();    setInterval(ensure, 1000);  }} catch (e) {{}}}})();"

def _browser_launch_error(message: str) -> RuntimeError:
    return RuntimeError(f'{message} {_BROWSER_LAUNCH_HINT}')

def _cdp_websocket_error(exc: Exception) -> RuntimeError:
    detail = str(exc).lower()
    if '403' in detail or 'forbidden' in detail or 'remote-allow-origins' in detail:
        message = 'Chrome/Edge blocked the CDP connection (often after a browser update). Connections requires --remote-allow-origins=* when launching the browser.'
    else:
        message = f'Could not connect to the browser debugging endpoint ({exc}).'
    return RuntimeError(f'{message} {_BROWSER_LAUNCH_HINT}')
_CHROMIUM_WHICH_NAMES = ('google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser', 'microsoft-edge', 'microsoft-edge-stable', 'brave-browser', 'brave')

def _chromium_executable_candidates() -> list[Path]:
    candidates: list[Path] = []
    if sys.platform == 'win32':
        pf = os.environ.get('ProgramFiles', 'C:\\Program Files')
        pfx = os.environ.get('ProgramFiles(x86)', 'C:\\Program Files (x86)')
        local = os.environ.get('LOCALAPPDATA', '')
        candidates.extend([Path(pf) / 'Google/Chrome/Application/chrome.exe', Path(pfx) / 'Google/Chrome/Application/chrome.exe', Path(local) / 'Google/Chrome/Application/chrome.exe', Path(pf) / 'Microsoft/Edge/Application/msedge.exe', Path(pfx) / 'Microsoft/Edge/Application/msedge.exe'])
        return candidates
    candidates.extend([Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'), Path('/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta'), Path('/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary'), Path('/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'), Path('/Applications/Brave Browser.app/Contents/MacOS/Brave Browser'), Path('/Applications/Chromium.app/Contents/MacOS/Chromium'), Path('/usr/bin/google-chrome'), Path('/usr/bin/google-chrome-stable'), Path('/usr/bin/chromium'), Path('/usr/bin/chromium-browser'), Path('/opt/google/chrome/chrome'), Path('/usr/bin/microsoft-edge'), Path('/usr/bin/microsoft-edge-stable'), Path('/usr/bin/brave-browser'), Path('/snap/bin/chromium'), Path('/snap/bin/google-chrome'), Path('/var/lib/flatpak/exports/bin/org.chromium.Chromium'), Path('/var/lib/flatpak/exports/bin/com.google.Chrome')])
    home = Path(os.path.expanduser('~'))
    candidates.extend([Path(os.path.join(home, '.local/share/flatpak/exports/bin/org.chromium.Chromium')), Path(os.path.join(home, '.local/share/flatpak/exports/bin/com.google.Chrome'))])
    return candidates

def find_chromium_executable() -> Path:
    override = os.getenv('BAKLOG_CHROME_PATH', '').strip()
    if override:
        p = Path(override)
        if p.is_file():
            return p
        raise RuntimeError(f'BAKLOG_CHROME_PATH does not exist: {override}')
    for path in _chromium_executable_candidates():
        if path.is_file():
            return path
    for name in _CHROMIUM_WHICH_NAMES:
        found = shutil.which(name)
        if found:
            p = Path(found)
            if p.is_file():
                return p
    raise RuntimeError('No Chrome or Edge browser found. Install Google Chrome or Microsoft Edge, or set BAKLOG_CHROME_PATH to your browser executable.')

def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return int(s.getsockname()[1])

def _fetch_json(url: str, timeout: float=5.0) -> Any:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8'))

@dataclass
class CdpRequest:
    url: str
    headers: dict[str, str]
    post_data: str = ''

    def __post_init__(self) -> None:
        self.headers = {k.lower(): v for k, v in (self.headers or {}).items()}

@dataclass
class CdpResponse:
    url: str
    status: int
    request: CdpRequest
    headers: dict[str, str]
    _page: CdpPage
    _request_id: str
    _body: str | None = None

    def __post_init__(self) -> None:
        self.headers = {k.lower(): v for k, v in (self.headers or {}).items()}

    def text(self) -> str:
        if self._body is None:
            self._body = self._page._get_response_body(self._request_id)
        return self._body

    def json(self) -> Any:
        return json.loads(self.text())

class _RequestProxy:

    def __init__(self, url: str, headers: dict[str, str]) -> None:
        self.url = url
        self.headers = {k.lower(): v for k, v in headers.items()}

class CdpLocator:

    def __init__(self, page: CdpPage, selector: str, *, index: int | None=None) -> None:
        self._page = page
        self._selector = selector
        self._index = index

    @property
    def first(self) -> CdpLocator:
        return CdpLocator(self._page, self._selector, index=0)

    def nth(self, i: int) -> CdpLocator:
        return CdpLocator(self._page, self._selector, index=i)

    def count(self) -> int:
        total = self._element_count()
        if self._index is not None:
            return 1 if self._index < total else 0
        return total

    def _element_count(self) -> int:
        sel = json.dumps(self._selector)
        n = self._page.evaluate(f"() => {{\n                const parts = {sel}.split(',').map(s => s.trim()).filter(Boolean);\n                const seen = new Set();\n                for (const p of parts) {{\n                    try {{\n                        document.querySelectorAll(p).forEach(el => seen.add(el));\n                    }} catch (e) {{}}\n                }}\n                return seen.size;\n            }}")
        return int(n or 0)

    def click(self, *, timeout: float=3000) -> None:
        idx = self._index if self._index is not None else 0
        sel = json.dumps(self._selector)
        ok = self._page.evaluate(f"() => {{\n                const parts = {sel}.split(',').map(s => s.trim()).filter(Boolean);\n                const els = [];\n                const seen = new Set();\n                for (const p of parts) {{\n                    try {{\n                        document.querySelectorAll(p).forEach(el => {{\n                            if (!seen.has(el)) {{ seen.add(el); els.push(el); }}\n                        }});\n                    }} catch (e) {{}}\n                }}\n                const el = els[{idx}];\n                if (!el) return false;\n                el.scrollIntoView({{block: 'center'}});\n                el.click();\n                return true;\n            }}")
        if not ok:
            raise RuntimeError(f'Could not click element: {self._selector!r}')

    def fill(self, value: str, *, timeout: float=2500) -> None:
        idx = self._index if self._index is not None else 0
        sel = json.dumps(self._selector)
        val = json.dumps(value)
        ok = self._page.evaluate(f"() => {{\n                const parts = {sel}.split(',').map(s => s.trim()).filter(Boolean);\n                const els = [];\n                const seen = new Set();\n                for (const p of parts) {{\n                    try {{\n                        document.querySelectorAll(p).forEach(el => {{\n                            if (!seen.has(el)) {{ seen.add(el); els.push(el); }}\n                        }});\n                    }} catch (e) {{}}\n                }}\n                const el = els[{idx}];\n                if (!el) return false;\n                el.focus();\n                el.value = {val};\n                el.dispatchEvent(new Event('input', {{ bubbles: true }}));\n                el.dispatchEvent(new Event('change', {{ bubbles: true }}));\n                return true;\n            }}")
        if not ok:
            raise RuntimeError(f'Could not fill element: {self._selector!r}')

class CdpPage:

    def __init__(self, context: CdpContext, target_id: str, session_id: str) -> None:
        self._context = context
        self._target_id = target_id
        self._session_id = session_id
        self._closed = False
        self._url = 'about:blank'
        self._request_handlers: list[Callable[[_RequestProxy], None]] = []
        self._response_handlers: list[Callable[[CdpResponse], None]] = []
        self._pending_requests: dict[str, CdpRequest] = {}
        self._pending_popup_url: str | None = None

    @property
    def url(self) -> str:
        try:
            result = self._context._send('Page.getNavigationHistory', session_id=self._session_id)
            entries = result.get('entries') or []
            idx = result.get('currentIndex', -1)
            if 0 <= idx < len(entries):
                self._url = entries[idx].get('url') or self._url
        except Exception:
            pass
        return self._url

    @property
    def is_closed(self) -> bool:
        return self._closed

    def on(self, event: str, handler: Callable) -> None:
        if event == 'request':
            self._request_handlers.append(handler)
        elif event == 'response':
            self._response_handlers.append(handler)

    def _dispatch_request(self, req: CdpRequest) -> None:
        proxy = _RequestProxy(req.url, req.headers)
        for h in self._request_handlers:
            try:
                h(proxy)
            except Exception:
                pass
        for h in self._context._request_handlers:
            try:
                h(proxy)
            except Exception:
                pass

    def _dispatch_response(self, resp: CdpResponse) -> None:
        for h in self._response_handlers:
            try:
                h(resp)
            except Exception:
                pass
        for h in self._context._response_handlers:
            try:
                h(resp)
            except Exception:
                pass

    def _handle_network_event(self, method: str, params: dict) -> None:
        if method == 'Network.requestWillBeSent':
            req_id = params.get('requestId', '')
            req_data = params.get('request') or {}
            post = req_data.get('postData') or ''
            headers = req_data.get('headers') or {}
            url = req_data.get('url') or ''
            cdp_req = CdpRequest(url=url, headers=headers, post_data=post)
            self._pending_requests[req_id] = cdp_req
            self._dispatch_request(cdp_req)
        elif method == 'Network.requestWillBeSentExtraInfo':
            req_id = params.get('requestId', '')
            extra = params.get('headers') or {}
            cdp_req = self._pending_requests.get(req_id)
            if cdp_req and extra:
                merged = dict(cdp_req.headers)
                merged.update({str(k).lower(): v for k, v in extra.items()})
                cdp_req.headers = merged
                self._dispatch_request(cdp_req)
        elif method == 'Network.responseReceived':
            req_id = params.get('requestId', '')
            resp_data = params.get('response') or {}
            cdp_req = self._pending_requests.get(req_id) or CdpRequest(url=resp_data.get('url') or '', headers={})
            status = int(resp_data.get('status') or 0)
            resp_headers = resp_data.get('headers') or {}
            cdp_resp = CdpResponse(url=cdp_req.url, status=status, request=cdp_req, headers=resp_headers, _page=self, _request_id=req_id)
            self._dispatch_response(cdp_resp)

    def _get_response_body(self, request_id: str) -> str:
        try:
            result = self._context._send('Network.getResponseBody', {'requestId': request_id}, session_id=self._session_id)
            body = result.get('body') or ''
            if result.get('base64Encoded'):
                import base64
                return base64.b64decode(body).decode('utf-8', errors='replace')
            return body
        except Exception:
            return ''

    def goto(self, url: str, *, wait_until: str='domcontentloaded', timeout: float=30000) -> None:
        self._context._send('Page.navigate', {'url': url}, session_id=self._session_id)
        if wait_until == 'commit':
            deadline = time.time() + timeout / 1000.0
            while time.time() < deadline:
                try:
                    result = self._context._send('Page.getNavigationHistory', session_id=self._session_id)
                    entries = result.get('entries') or []
                    idx = result.get('currentIndex', -1)
                    if 0 <= idx < len(entries):
                        nav_url = entries[idx].get('url') or ''
                        if nav_url and nav_url not in ('about:blank', ''):
                            self._url = nav_url
                            return
                except Exception:
                    pass
                time.sleep(0.15)
            return
        deadline = time.time() + timeout / 1000.0
        while time.time() < deadline:
            try:
                result = self._context._send('Page.getNavigationHistory', session_id=self._session_id)
                entries = result.get('entries') or []
                idx = result.get('currentIndex', -1)
                if 0 <= idx < len(entries):
                    self._url = entries[idx].get('url') or url
            except Exception:
                pass
            if wait_until == 'domcontentloaded':
                try:
                    ready = self.evaluate("() => document.readyState === 'complete' || document.readyState === 'interactive'", timeout=5)
                except Exception:
                    ready = False
                if ready:
                    return
            else:
                return
            time.sleep(0.15)
        raise TimeoutError(f'Navigation to {url!r} timed out after {timeout}ms')

    def go_back(self, *, wait_until: str='domcontentloaded', timeout: float=10000) -> None:
        self.evaluate('() => { history.back(); return true; }')
        self.wait_for_timeout(min(int(timeout), 2000))

    def evaluate(self, expression: str, *, timeout: float=60) -> Any:
        expr = expression.strip()
        if expr.startswith('(') or expr.startswith('function') or expr.startswith('async'):
            wrapped = f'({expr})()'
            if expr.startswith('async'):
                wrapped = f'({expr})()'
        else:
            wrapped = expr
        result = self._context._send('Runtime.evaluate', {'expression': wrapped, 'returnByValue': True, 'awaitPromise': True}, session_id=self._session_id, timeout=timeout)
        if result.get('exceptionDetails'):
            raise RuntimeError(str(result['exceptionDetails']))
        return (result.get('result') or {}).get('value')

    def content(self) -> str:
        html = self.evaluate("() => {\n                const d = document.documentElement;\n                return d ? d.outerHTML : '';\n            }")
        return html if isinstance(html, str) else ''

    def title(self) -> str:
        t = self.evaluate("() => document.title || ''")
        return t if isinstance(t, str) else ''

    def wait_for_timeout(self, ms: int) -> None:
        time.sleep(max(0, ms) / 1000.0)

    def bring_to_front(self) -> None:
        try:
            self._context._send('Page.bringToFront', session_id=self._session_id)
        except Exception:
            pass

    def focus_window(self) -> None:
        try:
            result = self._context._send('Browser.getWindowForTarget', {'targetId': self._target_id})
        except Exception:
            result = {}
        window_id = result.get('windowId')
        if window_id is None:
            self.bring_to_front()
            return
        bounds = result.get('bounds') or {}
        restore_state = bounds.get('windowState') or 'normal'
        if restore_state == 'minimized':
            restore_state = 'normal'
        try:
            self._context._send('Browser.setWindowBounds', {'windowId': window_id, 'bounds': {'windowState': 'minimized'}})
            self._context._send('Browser.setWindowBounds', {'windowId': window_id, 'bounds': {'windowState': restore_state}})
        except Exception:
            pass
        self.bring_to_front()

    def close(self, *, timeout: float=60) -> None:
        if self._closed:
            return
        try:
            self._context._send('Target.closeTarget', {'targetId': self._target_id}, timeout=timeout)
        except Exception:
            pass
        self._closed = True
        if self in self._context.pages:
            self._context.pages.remove(self)

    def locator(self, selector: str) -> CdpLocator:
        return CdpLocator(self, selector)

    def get_by_role(self, role: str, *, name: re.Pattern[str] | str | None=None) -> CdpLocator:
        pattern = name.pattern if isinstance(name, re.Pattern) else str(name) if name else ''
        flags = name.flags if isinstance(name, re.Pattern) else re.I
        return _RoleLocator(self, role, pattern, flags)

class _RoleLocator:

    def __init__(self, page: CdpPage, role: str, pattern: str, flags: int) -> None:
        self._page = page
        self._role = role.lower()
        self._pattern = pattern
        self._flags = flags

    @property
    def first(self) -> _RoleLocator:
        return self

    def count(self) -> int:
        return 1 if self._clickable() else 0

    def click(self, *, timeout: float=3000) -> None:
        if not self._clickable(click=True):
            raise RuntimeError(f'No {self._role!r} matching {self._pattern!r}')

    def _clickable(self, *, click: bool=False) -> bool:
        role = json.dumps(self._role)
        pat = json.dumps(self._pattern)
        flag_str = 'i' if self._flags & re.IGNORECASE else ''
        return bool(self._page.evaluate(f"""() => {{\n                    const role = {role};\n                    const pat = {pat};\n                    const re = new RegExp(pat, '{flag_str}');\n                    const nodes = document.querySelectorAll('[role="' + role + '"],' + role);\n                    for (const el of nodes) {{\n                        const label = (el.getAttribute('aria-label') || el.innerText || '').trim();\n                        if (!pat || re.test(label)) {{\n                            {('el.click(); return true;' if click else 'return true;')}\n                        }}\n                    }}\n                    // Also match native buttons by innerText\n                    if (role === 'button') {{\n                        for (const el of document.querySelectorAll('button, input[type="submit"]')) {{\n                            const label = (el.innerText || el.value || '').trim();\n                            if (!pat || re.test(label)) {{\n                                {('el.click(); return true;' if click else 'return true;')}\n                            }}\n                        }}\n                    }}\n                    return false;\n                }}"""))

class CdpHttpResponse:

    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self._body = body

    def text(self) -> str:
        return self._body

    def json(self) -> dict:
        return json.loads(self._body)

class CdpHttpClient:

    def __init__(self, context: CdpContext) -> None:
        self._context = context

    def _cookie_jar(self) -> dict[str, str]:
        cookies = self._context.cookies()
        return {c['name']: c['value'] for c in cookies if c.get('name')}

    def _base_headers(self, headers: dict[str, str] | None) -> dict[str, str]:
        req_headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'}
        if headers:
            req_headers.update(headers)
        return req_headers

    def get(self, url: str, *, headers: dict[str, str] | None=None, timeout: float=30000) -> CdpHttpResponse:
        resp = requests.get(url, cookies=self._cookie_jar(), headers=self._base_headers(headers), timeout=timeout / 1000.0)
        return CdpHttpResponse(resp.status_code, resp.text)

    def post(self, url: str, *, headers: dict[str, str] | None=None, data: str | None=None, json: dict | None=None, timeout: float=30000) -> CdpHttpResponse:
        resp = requests.post(url, cookies=self._cookie_jar(), headers=self._base_headers(headers), data=data, json=json, timeout=timeout / 1000.0)
        return CdpHttpResponse(resp.status_code, resp.text)

class CdpContext:

    def __init__(self, *, proc: subprocess.Popen[Any], port: int, ws: websocket.WebSocket, send_lock: threading.Lock, pending: dict[int, dict], event_handlers: dict[str, list[Callable]]) -> None:
        self._proc = proc
        self._port = port
        self._ws = ws
        self._send_lock = send_lock
        self._pending = pending
        self._event_handlers = event_handlers
        self.pages: list[CdpPage] = []
        self._pages_by_session: dict[str, CdpPage] = {}
        self._pages_by_target: dict[str, CdpPage] = {}
        self._request_handlers: list[Callable[[_RequestProxy], None]] = []
        self._response_handlers: list[Callable[[CdpResponse], None]] = []
        self._init_scripts: list[str] = []
        self._page_handlers: list[Callable[[CdpPage], None]] = []
        self._ubisoft_native_popup_targets: set[str] = set()
        self._ws_dead = False
        self.request = CdpHttpClient(self)

    def on(self, event: str, handler: Callable) -> None:
        if event == 'page':
            self._page_handlers.append(handler)
        elif event == 'request':
            self._request_handlers.append(handler)
        elif event == 'response':
            self._response_handlers.append(handler)

    def add_init_script(self, source: str) -> None:
        self._init_scripts.append(source)
        for page in self.pages:
            self._apply_init_script(page, source)

    def set_auth_banner(self, message: str) -> None:
        if not message:
            return
        fn = f'() => {{ try {{ if (window.__baklogSetBanner) window.__baklogSetBanner({json.dumps(message)}); }} catch (e) {{}} }}'
        for page in list(self.pages):
            if getattr(page, 'is_closed', False):
                continue
            try:
                page.evaluate(fn, timeout=5)
            except Exception:
                pass

    def _apply_init_script(self, page: CdpPage, source: str) -> None:
        try:
            self._send('Page.addScriptToEvaluateOnNewDocument', {'source': source}, session_id=page._session_id)
        except Exception:
            pass

    def _first_page_session(self) -> str | None:
        for page in self.pages:
            if not page.is_closed and page._session_id:
                return page._session_id
        page = self.new_page()
        return page._session_id or None

    def cookies(self) -> list[dict[str, Any]]:
        sid = self._first_page_session()
        result: dict[str, Any] = {}
        if sid:
            try:
                result = self._send('Network.getAllCookies', session_id=sid)
            except Exception:
                result = {}
        if not result.get('cookies'):
            try:
                result = self._send('Storage.getCookies')
            except Exception:
                result = result or {}
        out: list[dict[str, Any]] = []
        for c in result.get('cookies') or []:
            out.append({'name': c.get('name', ''), 'value': c.get('value', ''), 'domain': c.get('domain', '')})
        return out

    def new_page(self) -> CdpPage:
        result = self._send('Target.createTarget', {'url': 'about:blank'})
        target_id = result.get('targetId', '')
        page = self._attach_page(target_id)
        if page not in self.pages:
            self.pages.append(page)
        return page

    def _register_page(self, target_id: str, session_id: str) -> CdpPage:
        page = CdpPage(self, target_id, session_id)
        self._pages_by_session[session_id] = page
        self._pages_by_target[target_id] = page
        self._send('Page.enable', session_id=session_id)
        self._send('Runtime.enable', session_id=session_id)
        self._send('Network.enable', {'includeExtraInfo': True}, session_id=session_id)
        for src in self._init_scripts:
            self._apply_init_script(page, src)
        return page

    def _attach_page(self, target_id: str) -> CdpPage:
        if target_id in self._pages_by_target:
            return self._pages_by_target[target_id]
        result = self._send('Target.attachToTarget', {'targetId': target_id, 'flatten': True})
        session_id = result.get('sessionId', '')
        return self._register_page(target_id, session_id)

    def _merge_popup_worker(self, page: CdpPage) -> None:
        try:
            deadline = time.time() + _POPUP_URL_WAIT_SEC
            url = ''
            while time.time() < deadline:
                url = (page.url or '').strip()
                if url and (not is_blank_browser_url(url)):
                    break
                time.sleep(0.25)
            url = (page.url or '').strip()
            others = [p for p in self.pages if p is not page and (not p.is_closed)]
            if _should_preserve_popup(url):
                if not is_blank_browser_url(url):
                    try:
                        page.bring_to_front()
                    except Exception:
                        pass
                return
            try:
                page.close()
            except Exception:
                pass
            main = others[0] if others else self.new_page()
            try:
                main.bring_to_front()
            except Exception:
                pass
            try:
                main.goto(url, wait_until='domcontentloaded', timeout=30000)
            except Exception:
                pass
        except Exception:
            pass
        finally:
            for h in self._page_handlers:
                try:
                    h(page)
                except Exception:
                    pass

    def _handle_event(self, method: str, params: dict, session_id: str | None) -> None:
        if method == 'Target.attachedToTarget':
            threading.Thread(target=self._on_attached_to_target, args=(params,), daemon=True).start()
            return
        if method == 'Target.targetDestroyed':
            target_id = params.get('targetId', '')
            page = self._pages_by_target.pop(target_id, None)
            if page:
                page._closed = True
                if page in self.pages:
                    self.pages.remove(page)
            return
        if method == 'Target.targetCreated':
            _info = params.get('targetInfo') or {}
            if _info.get('type') == 'page':
                threading.Thread(target=self._on_target_created, args=(_info,), daemon=True).start()
            return
        if method == 'Target.targetInfoChanged':
            info = params.get('targetInfo') or {}
            target_id = info.get('targetId', '')
            page = self._pages_by_target.get(target_id)
            new_url = (info.get('url') or '').strip()
            if page:
                if new_url:
                    page._url = new_url
            return
        page = self._pages_by_session.get(session_id or '')
        if page and method == 'Page.windowOpen':
            open_url = (params.get('url') or '').strip()
            if open_url:
                page._pending_popup_url = open_url
        if page and method.startswith('Network.'):
            page._handle_network_event(method, params)

    def _pending_ubisoft_login_url(self, opener_id: str) -> str | None:
        opener = self._pages_by_target.get(opener_id)
        if not opener:
            return None
        deadline = time.time() + 1.0
        while time.time() < deadline:
            pending = (getattr(opener, '_pending_popup_url', None) or '').strip()
            if 'connect.ubisoft.com/login' in pending.lower():
                return pending
            time.sleep(0.05)
        return None

    def _on_target_created(self, info: dict) -> None:
        target_id = info.get('targetId', '')
        if not target_id or target_id in self._pages_by_target:
            return
        if target_id in self._ubisoft_native_popup_targets:
            return
        opener_id = str(info.get('openerId') or info.get('openerFrameId') or '')
        popup_url = (info.get('url') or '').strip()
        if opener_id and is_blank_browser_url(popup_url):
            login_url = self._pending_ubisoft_login_url(opener_id)
            if login_url:
                self._ubisoft_native_popup_targets.add(target_id)
                return
        try:
            self._send('Target.attachToTarget', {'targetId': target_id, 'flatten': True})
        except Exception:
            pass

    def _on_attached_to_target(self, params: dict) -> None:
        info = params.get('targetInfo') or {}
        sid = params.get('sessionId') or ''
        target_id = info.get('targetId', '')
        if info.get('type') != 'page' or not sid or (not target_id):
            return
        if target_id in self._ubisoft_native_popup_targets:
            try:
                self._send('Target.detachFromTarget', {'sessionId': sid})
            except Exception:
                pass
            return
        if target_id in self._pages_by_target:
            return
        page = self._register_page(target_id, sid)
        if page not in self.pages:
            self.pages.append(page)
        self._maybe_navigate_blank_popup(page, info)
        if len(self.pages) > 1:
            threading.Thread(target=self._merge_popup_worker, args=(page,), daemon=True).start()

    def _maybe_navigate_blank_popup(self, page: CdpPage, info: dict) -> None:
        opener_id = str(info.get('openerId') or info.get('openerFrameId') or '')
        if not opener_id:
            return
        opener = self._pages_by_target.get(opener_id)
        if not opener:
            return
        target_url = (getattr(opener, '_pending_popup_url', None) or '').strip()
        if not target_url:
            return
        current = (info.get('url') or page._url or '').strip()
        if not is_blank_browser_url(current):
            return

        def _nav() -> None:
            url = target_url
            deadline = time.time() + 2.0
            while not url and time.time() < deadline:
                time.sleep(0.05)
                url = (getattr(opener, '_pending_popup_url', None) or '').strip()
            if not url:
                return
            try:
                page.goto(url, wait_until='commit', timeout=15000)
            except Exception:
                pass
        threading.Thread(target=_nav, daemon=True).start()

    def _send(self, method: str, params: dict | None=None, *, session_id: str | None=None, timeout: float=60) -> dict:
        if self._ws_dead:
            raise ConnectionError('CDP connection closed')
        msg_id = self._next_id()
        payload: dict[str, Any] = {'id': msg_id, 'method': method, 'params': params or {}}
        if session_id:
            payload['sessionId'] = session_id
        with self._send_lock:
            self._pending[msg_id] = {'done': threading.Event(), 'result': None, 'error': None}
            self._ws.send(json.dumps(payload))
            ev = self._pending[msg_id]['done']
        if not ev.wait(timeout=timeout):
            self._pending.pop(msg_id, None)
            raise TimeoutError(f'CDP command timed out: {method}')
        entry = self._pending.pop(msg_id, {})
        if entry.get('error'):
            raise RuntimeError(entry['error'])
        return entry.get('result') or {}
    _id_counter = 0
    _id_lock = threading.Lock()

    def _next_id(self) -> int:
        with CdpContext._id_lock:
            CdpContext._id_counter += 1
            return CdpContext._id_counter

    def close(self) -> None:
        port = int(getattr(self, '_port', 0) or 0)
        for page in list(getattr(self, 'pages', ())):
            try:
                if not page.is_closed:
                    page.close(timeout=5)
            except Exception:
                pass
        try:
            self._send('Browser.close', timeout=5)
        except Exception:
            pass
        if self._proc.poll() is None:
            try:
                self._proc.wait(timeout=8)
            except Exception:
                pass
        try:
            self._ws.close()
        except Exception:
            pass
        if self._proc.poll() is None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
        port_pids = _pids_listening_on_local_port(port)
        if port_pids:
            _kill_pids(port_pids)

    def __enter__(self) -> CdpContext:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

class ConnectBrowserClosed(Exception):

def browser_session_gone(context: CdpContext | Any) -> bool:
    if getattr(context, '_ws_dead', False):
        return True
    pages = list(getattr(context, 'pages', ()) or ())
    if pages:
        return all((p.is_closed for p in pages))
    return False

def abort_if_browser_closed(context: CdpContext | Any) -> None:
    if browser_session_gone(context):
        raise ConnectBrowserClosed()

def _reader_loop(ws: websocket.WebSocket, pending: dict[int, dict], context: CdpContext | None) -> None:
    while True:
        try:
            raw = ws.recv()
            if not raw:
                break
            msg = json.loads(raw)
        except Exception:
            break
        if 'id' in msg:
            mid = msg['id']
            entry = pending.get(mid)
            if entry:
                if 'error' in msg:
                    entry['error'] = msg['error'].get('message', str(msg['error']))
                else:
                    entry['result'] = msg.get('result') or {}
                entry['done'].set()
        elif 'method' in msg and context:
            context._handle_event(msg['method'], msg.get('params') or {}, msg.get('sessionId'))
    if context is not None:
        context._ws_dead = True
    for entry in list(pending.values()):
        if entry.get('error') is None and entry.get('result') is None:
            entry['error'] = 'CDP connection closed'
        entry['done'].set()

def _ensure_persistent_session_prefs(profile: Path) -> None:
    try:
        default_dir = profile / 'Default'
        default_dir.mkdir(parents=True, exist_ok=True)
        prefs_path = default_dir / 'Preferences'
        prefs: dict[str, Any] = {}
        if prefs_path.exists():
            try:
                loaded = json.loads(prefs_path.read_text(encoding='utf-8'))
                if isinstance(loaded, dict):
                    prefs = loaded
            except (json.JSONDecodeError, OSError):
                prefs = {}
        session = prefs.get('session')
        if not isinstance(session, dict):
            session = {}
        session['restore_on_startup'] = 1
        prefs['session'] = session
        profile_node = prefs.get('profile')
        if not isinstance(profile_node, dict):
            profile_node = {}
        profile_node['exit_type'] = 'Normal'
        profile_node['exited_cleanly'] = True
        profile_node['password_manager_enabled'] = True
        prefs['profile'] = profile_node
        prefs['credentials_enable_service'] = True
        prefs['credentials_enable_autosignin'] = True
        prefs_path.write_text(json.dumps(prefs), encoding='utf-8')
    except OSError:
        pass

def launch_persistent_profile(user_data_dir: str | Path, *, headless: bool | str=False, window_position: tuple[int, int] | None=None, window_size: tuple[int, int] | None=None, start_minimized: bool=False, initial_url: str | None=None) -> CdpContext:
    exe = find_chromium_executable()
    port = _free_port()
    profile = Path(user_data_dir)
    profile.mkdir(parents=True, exist_ok=True)
    _ensure_persistent_session_prefs(profile)
    args = [str(exe), f'--user-data-dir={profile}', f'--remote-debugging-port={port}', '--remote-allow-origins=http://127.0.0.1,http://localhost,http://[::1]', '--no-first-run', '--no-default-browser-check', '--disable-extensions', '--disable-features=IsolateOrigins,site-per-process']
    if headless:
        mode = 'new' if headless is True else str(headless).lower()
        if mode in ('legacy', 'old'):
            args.append('--headless')
        else:
            args.append('--headless=new')
        args.append('--window-size=1920,1080')
    elif window_position is not None:
        wx, wy = window_position
        ww, wh = window_size if window_size is not None else (1280, 900)
        args.append(f'--window-position={wx},{wy}')
        args.append(f'--window-size={ww},{wh}')
    elif start_minimized:
        ww, wh = window_size if window_size is not None else (1280, 900)
        args.append('--start-minimized')
        args.append(f'--window-size={ww},{wh}')
    else:
        args.append('--start-maximized')
    proc: subprocess.Popen[Any] | None = None
    ws_url = None
    released_pids: list[int] = []
    for attempt in range(2):
        proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0)
        deadline = time.time() + 30
        while time.time() < deadline:
            if proc.poll() is not None:
                exit_code = proc.returncode
                proc.kill()
                if attempt == 0 and exit_code == 21:
                    released_pids = release_chromium_profile_lock(profile)
                    break
                hint = 'Close any other window using this profile and try again.' if not released_pids else 'A stale sign-in window was still using this profile; try Reconnect again.'
                raise _browser_launch_error(f'Browser exited immediately (code {exit_code}). {hint} Install Google Chrome or Microsoft Edge, set BAKLOG_CHROME_PATH to the browser executable, or try the other installed browser.')
            try:
                version = _fetch_json(f'http://127.0.0.1:{port}/json/version', timeout=2)
                ws_url = version.get('webSocketDebuggerUrl')
                if ws_url:
                    break
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
                pass
            time.sleep(0.2)
        if ws_url:
            break
    if not ws_url:
        if proc is not None:
            proc.kill()
        raise _browser_launch_error('Browser did not start CDP debugging endpoint in time.')
    try:
        ws = websocket.create_connection(ws_url, timeout=60, origin='http://127.0.0.1')
    except Exception as exc:
        proc.kill()
        raise _cdp_websocket_error(exc) from exc
    send_lock = threading.Lock()
    pending: dict[int, dict] = {}
    context = CdpContext(proc=proc, port=port, ws=ws, send_lock=send_lock, pending=pending, event_handlers={})
    threading.Thread(target=_reader_loop, args=(ws, pending, context), daemon=True).start()
    context._send('Target.setAutoAttach', {'autoAttach': False, 'waitForDebuggerOnStart': False, 'flatten': True})
    context._send('Target.setDiscoverTargets', {'discover': True})
    targets = _fetch_json(f'http://127.0.0.1:{port}/json/list', timeout=5)
    page_targets = [t for t in targets if t.get('type') == 'page']
    for t in page_targets:
        page = context._attach_page(t['id'])
        if page not in context.pages:
            context.pages.append(page)
    if not context.pages:
        deadline = time.time() + 10.0
        last_err = ''
        while time.time() < deadline and (not context.pages):
            try:
                context.new_page()
            except Exception as exc:
                last_err = str(exc)
                time.sleep(0.25)
        if not context.pages:
            raise RuntimeError(last_err or 'Browser did not expose a connect page')
    context.add_init_script(_AUTOMATION_MASK_SCRIPT)
    if initial_url:
        page = next((p for p in context.pages if not p.is_closed), None)
        if page is None:
            try:
                page = context.new_page()
            except Exception:
                page = None
        if page is not None:
            try:
                page.goto(initial_url, wait_until='domcontentloaded', timeout=25000)
            except Exception:
                pass
    return context

def is_blank_browser_url(url: str) -> bool:
    return (url or '').strip() in _BLANK_URLS
_POPUP_MERGE_READY = re.compile('connect\\.ubisoft\\.com/logged-in\\.html', re.I)
_POPUP_AUTH_PATTERNS = re.compile('(?:login|signin|sign-in|authorize|oauth|account\\.|connect\\.)', re.I)

def _should_preserve_popup(url: str) -> bool:
    u = (url or '').strip()
    if is_blank_browser_url(u):
        return True
    if _POPUP_MERGE_READY.search(u):
        return False
    if _POPUP_AUTH_PATTERNS.search(u):
        return True
    return False
_POPUP_URL_WAIT_SEC = 45