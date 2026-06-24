"""SSE stream ticket mint/consume (EventSource cannot send Authorization headers)."""

from __future__ import annotations

import secrets
import threading
import time
from http.server import SimpleHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

_stream_tickets: dict[str, tuple[str, float, int, str | None]] = {}
_stream_tickets_lock = threading.Lock()

STREAM_TICKET_TTL_SEC = 90.0
# EventSource auto-reconnects with the same URL; single-use tickets caused 401
# loops when a failed connect (404/503) consumed the ticket first.
STREAM_TICKET_MAX_USES = 12
# Block the stream handler briefly on first connect so a run submitted on another
# dev-server process (split-brain on localhost) can finish and land in shared history.
STREAM_ATTACH_SHORT_WAIT_SEC = 2.0
STREAM_ATTACH_LONG_WAIT_SEC = 300.0
STREAM_ATTACH_POLL_SEC = 0.1


def _prune_expired_stream_tickets() -> None:
    now = time.time()
    expired = [k for k, (_, exp, _uses, _run) in _stream_tickets.items() if exp < now]
    for k in expired:
        _stream_tickets.pop(k, None)


def mint_stream_ticket(profile_id: str, *, run_id: str | None = None) -> str:
    ticket = secrets.token_urlsafe(32)
    with _stream_tickets_lock:
        _prune_expired_stream_tickets()
        _stream_tickets[ticket] = (
            profile_id,
            time.time() + STREAM_TICKET_TTL_SEC,
            STREAM_TICKET_MAX_USES,
            run_id,
        )
    return ticket


def peek_stream_ticket(ticket: str | None, run_id: str | None = None) -> str | None:
    """Validate a ticket without consuming a use (404/503 must not burn tickets)."""
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
        if bound_run and run_id and bound_run != run_id:
            return None
    return profile_id


def commit_stream_ticket(ticket: str | None, run_id: str | None = None) -> str | None:
    """Consume one ticket use once the stream endpoint is ready to respond."""
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
        if bound_run and run_id and bound_run != run_id:
            return None
        if uses_left <= 1:
            _stream_tickets.pop(ticket, None)
        else:
            _stream_tickets[ticket] = (profile_id, expiry, uses_left - 1, bound_run)
    return profile_id


def consume_stream_ticket(ticket: str | None) -> str | None:
    """Legacy single-use consume for auth-provider SSE (no run binding)."""
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


def stream_ticket_from_handler(handler: SimpleHTTPRequestHandler) -> str | None:
    parsed = urlparse(handler.path)
    raw = (parse_qs(parsed.query).get("ticket") or [None])[0]
    if raw is None:
        return None
    return str(raw).strip() or None
