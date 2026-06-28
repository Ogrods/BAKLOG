import secrets
import threading
import time
from urllib.parse import parse_qs, urlparse

_stream_tickets = {}
_stream_tickets_lock = threading.Lock()
STREAM_TICKET_TTL_SEC = 90.0
STREAM_TICKET_MAX_USES = 12
STREAM_ATTACH_SHORT_WAIT_SEC = 2.0
STREAM_ATTACH_LONG_WAIT_SEC = 300.0
STREAM_ATTACH_POLL_SEC = 0.1


def _prune_expired_stream_tickets():
    now = time.time()
    expired = [k for k, (_, exp, _uses, _run) in _stream_tickets.items() if exp < now]
    for k in expired:
        _stream_tickets.pop(k, None)


def mint_stream_ticket(profile_id, *, run_id=None):
    ticket = secrets.token_urlsafe(32)
    with _stream_tickets_lock:
        _prune_expired_stream_tickets()
        _stream_tickets[ticket] = (profile_id, time.time() + STREAM_TICKET_TTL_SEC, STREAM_TICKET_MAX_USES, run_id)
    return ticket


def peek_stream_ticket(ticket, run_id=None):
    if not ticket:
        return None
    now = time.time()
    with _stream_tickets_lock:
        entry = _stream_tickets.get(ticket)
        if not entry:
            return None
        profile_id, expiry, _uses_left, bound_run = entry
        if expiry < now:
            return None
        if bound_run and run_id and (bound_run != run_id):
            return None
    return profile_id


def commit_stream_ticket(ticket, run_id=None):
    if not ticket:
        return None
    now = time.time()
    with _stream_tickets_lock:
        entry = _stream_tickets.get(ticket)
        if not entry:
            return None
        profile_id, expiry, uses_left, bound_run = entry
        if expiry < now:
            _stream_tickets.pop(ticket, None)
            return None
        if bound_run and run_id and (bound_run != run_id):
            return None
        if uses_left <= 1:
            _stream_tickets.pop(ticket, None)
        else:
            _stream_tickets[ticket] = (profile_id, expiry, uses_left - 1, bound_run)
    return profile_id


def consume_stream_ticket(ticket):
    if not ticket:
        return None
    with _stream_tickets_lock:
        entry = _stream_tickets.pop(ticket, None)
    if not entry:
        return None
    profile_id, expiry, _uses_left, _bound_run = entry
    if expiry < time.time():
        return None
    return profile_id


def stream_ticket_from_handler(handler):
    parsed = urlparse(handler.path)
    raw = (parse_qs(parsed.query).get("ticket") or [None])[0]
    if raw is None:
        return None
    return str(raw).strip() or None
