from __future__ import annotations
import threading
import time
epic_oauth_states: dict[str, tuple[float, str]] = {}
_epic_oauth_states_lock = threading.Lock()

def _prune_expired_epic_oauth_states() -> None:
    now = time.monotonic()
    expired = [k for k, (exp, _) in epic_oauth_states.items() if exp < now]
    for k in expired:
        epic_oauth_states.pop(k, None)

def register_epic_oauth_state(state: str, profile_id: str | None=None, *, ttl_sec: float=600.0) -> None:
    from shared.profile_paths import get_active_profile_id
    pid = profile_id or get_active_profile_id()
    with _epic_oauth_states_lock:
        _prune_expired_epic_oauth_states()
        epic_oauth_states[state] = (time.monotonic() + ttl_sec, pid)

def consume_epic_oauth_state(state: str | None) -> str | None:
    if not state:
        return None
    with _epic_oauth_states_lock:
        entry = epic_oauth_states.pop(state, None)
    if not entry:
        return None
    expires, profile_id = entry
    if expires < time.monotonic():
        return None
    return profile_id

def handle_epic_oauth_callback(handler) -> None:
    import html
    from http import HTTPStatus
    from urllib.parse import parse_qs, urlparse
    from shared.profile_paths import set_request_profile_id
    parsed = urlparse(handler.path)
    params = parse_qs(parsed.query)
    code = (params.get('code') or [None])[0]
    state = (params.get('state') or [None])[0]
    if not state:
        handler.send_response(HTTPStatus.BAD_REQUEST)
        handler.send_header('Content-Type', 'text/html; charset=utf-8')
        body = b'<html><body><p>Missing OAuth state.</p></body></html>'
        handler.send_header('Content-Length', str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
        return
    profile_id = consume_epic_oauth_state(state)
    if profile_id is None:
        handler.send_response(HTTPStatus.BAD_REQUEST)
        handler.send_header('Content-Type', 'text/html; charset=utf-8')
        body = b'<html><body><p>Invalid or expired OAuth state.</p></body></html>'
        handler.send_header('Content-Length', str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
        return
    set_request_profile_id(profile_id)
    if not code:
        handler.send_response(HTTPStatus.BAD_REQUEST)
        handler.send_header('Content-Type', 'text/html; charset=utf-8')
        body = b'<html><body><p>Missing authorization code.</p></body></html>'
        handler.send_header('Content-Length', str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
        return
    try:
        from auth.manager import mark_connected
        from clients.epic_client import EpicClient, default_epic_cache_dir
        client = EpicClient(auth_code=code, cache_dir=default_epic_cache_dir())
        client.login()
        mark_connected('epic', {'EPIC_AUTH_CODE': code})
        body = b"<html><body><p>Epic connected. You can close this tab and return to the dashboard.</p><script>try{const c=new BroadcastChannel('baklog-auth');c.postMessage({provider:'epic'});c.close();}catch(e){}setTimeout(()=>window.close(),1500)</script></body></html>"
        handler.send_response(HTTPStatus.OK)
        handler.send_header('Content-Type', 'text/html; charset=utf-8')
        handler.send_header('Content-Length', str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
    except Exception as exc:
        safe = html.escape(str(exc), quote=True)
        body = f'<html><body><p>Epic sign-in failed: {safe}</p></body></html>'.encode()
        handler.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
        handler.send_header('Content-Type', 'text/html; charset=utf-8')
        handler.send_header('Content-Length', str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)