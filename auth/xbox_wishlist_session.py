from __future__ import annotations
import time
from typing import Literal
from auth.cdp_browser import launch_persistent_profile
from auth.runner import _STEALTH_INIT, XBOX_WISHLIST_POLL_SEC, XBOX_WISHLIST_URL, _parse_xbox_preloaded_state
from auth.secrets import profile_dir
HeadlessMode = bool | Literal['legacy', 'old', 'new']
_MAX_SIGNED_OUT_ATTEMPTS = 3

def _state_ready(state: dict) -> bool:
    user = state.get('user') or {}
    if not user.get('isSignedIn'):
        return False
    page_meta = (state.get('pageRequestMetadata') or {}).get('/wishlist') or {}
    err = page_meta.get('error') or {}
    return err.get('httpStatusCode') != 403

def _capture_once(*, headless: HeadlessMode, timeout_s: int) -> dict:
    profile = profile_dir('xbox_wishlist')
    if not profile.exists():
        raise RuntimeError("No saved Xbox wishlist profile at cache/auth/profiles/xbox_wishlist. Open the Connections page and connect 'Xbox Store wishlist' first.")
    deadline = time.time() + timeout_s
    last_state: dict | None = None
    signed_out_streak = 0
    with launch_persistent_profile(str(profile), headless=headless) as ctx:
        ctx.add_init_script(_STEALTH_INIT)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        while time.time() < deadline:
            if ctx._proc.poll() is not None:
                raise RuntimeError(f'Browser exited during wishlist capture (code {ctx._proc.returncode})')
            remaining_ms = max(5000, int((deadline - time.time()) * 1000))
            try:
                page.goto(XBOX_WISHLIST_URL, wait_until='domcontentloaded', timeout=min(20000, remaining_ms))
            except Exception as exc:
                err = str(exc).lower()
                if 'socket is already closed' in err or 'connection' in err:
                    raise RuntimeError('Browser connection lost during xbox.com/wishlist capture') from exc
                page.wait_for_timeout(int(XBOX_WISHLIST_POLL_SEC * 1000))
                if time.time() >= deadline:
                    raise RuntimeError(f'xbox.com/wishlist navigation failed: {exc}') from exc
                continue
            page.wait_for_timeout(2500)
            html = page.content()
            state = _parse_xbox_preloaded_state(html)
            if not state:
                signed_out_streak = 0
                page.wait_for_timeout(int(XBOX_WISHLIST_POLL_SEC * 1000))
                continue
            last_state = state
            if _state_ready(state):
                return state
            signed_out_streak += 1
            if signed_out_streak >= _MAX_SIGNED_OUT_ATTEMPTS:
                break
            page.wait_for_timeout(int(XBOX_WISHLIST_POLL_SEC * 1000))
    if last_state is not None:
        return last_state
    raise RuntimeError('Could not find __PRELOADED_STATE__ in the xbox.com/wishlist HTML response.')

def capture_xbox_wishlist_preloaded_state(*, headless: HeadlessMode='legacy', timeout_s: int=30) -> dict:
    return _capture_once(headless=headless, timeout_s=timeout_s)

def validate_xbox_wishlist_state(state: dict, *, headless: bool=True) -> str | None:
    user = state.get('user') or {}
    if not user.get('isSignedIn'):
        mode = 'headless' if headless else 'headed'
        return f'Xbox wishlist session is not signed in ({mode} SSR: user.isSignedIn=false). Reconnect on the Connections page and keep the sign-in window open until it closes.'
    page_meta = (state.get('pageRequestMetadata') or {}).get('/wishlist') or {}
    err = page_meta.get('error') or {}
    if err.get('httpStatusCode') == 403:
        return 'Signed in to Microsoft but xbox.com has not issued your wishlist token yet. Wait a moment on the wishlist page and try Reconnect again.'
    return None