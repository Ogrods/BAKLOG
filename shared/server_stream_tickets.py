"""SSE stream ticket mint/consume (EventSource cannot send Authorization headers)."""

from __future__ import annotations

import secrets
import threading
import time
from http.server import SimpleHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

# profile_id, expiry, uses_left, kind ("run"|"auth"), bound_id (run_id|session_id|None)
_stream_tickets: dict[str, tuple[str, float, int, str, str | None]] = {}
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

KIND_RUN = "run"
KIND_AUTH = "auth"


def _prune_expired_stream_tickets() -> None:
    now = time.time()
    expired = [k for k, (_, exp, _uses, _kind, _bound) in _stream_tickets.items() if exp < now]
    for k in expired:
        _stream_tickets.pop(k, None)


def mint_stream_ticket(
    profile_id: str,
    *,
    run_id: str | None = None,
    session_id: str | None = None,
) -> str:
    """Mint a limited-reuse SSE ticket.

    ``session_id`` → auth-kind ticket bound to that Connect session.
    ``run_id`` (or neither) → run-kind ticket; optional run binding.
    """
    if session_id and run_id:
        raise ValueError("run_id and session_id are mutually exclusive")
    if session_id is not None:
        bound = str(session_id).strip() or None
        if not bound:
            raise ValueError("session_id required for auth stream tickets")
        kind = KIND_AUTH
    else:
        kind = KIND_RUN
        bound = (str(run_id).strip() or None) if run_id else None
    ticket = secrets.token_urlsafe(32)
    with _stream_tickets_lock:
        _prune_expired_stream_tickets()
        _stream_tickets[ticket] = (
            profile_id,
            time.time() + STREAM_TICKET_TTL_SEC,
            STREAM_TICKET_MAX_USES,
            kind,
            bound,
        )
    return ticket


def _ticket_matches(
    kind: str,
    bound_id: str | None,
    *,
    run_id: str | None,
    session_id: str | None,
    expect_kind: str | None,
) -> bool:
    if expect_kind and kind != expect_kind:
        return False
    if expect_kind == KIND_AUTH or session_id is not None:
        if kind != KIND_AUTH:
            return False
        want = (session_id or "").strip()
        if not want or bound_id != want:
            return False
        return True
    # Run stream path: reject auth tickets; enforce run binding when present.
    if kind != KIND_RUN:
        return False
    if bound_id and run_id and bound_id != run_id:
        return False
    return True


def peek_stream_ticket(
    ticket: str | None,
    run_id: str | None = None,
    *,
    session_id: str | None = None,
    expect_kind: str | None = None,
) -> str | None:
    """Validate a ticket without consuming a use (404/503 must not burn tickets)."""
    if not ticket:
        return None
    now = time.time()
    with _stream_tickets_lock:
        entry = _stream_tickets.get(ticket)
        if not entry:
            return None
        profile_id, expiry, _uses_left, kind, bound_id = entry
        if expiry < now:
            return None
        if not _ticket_matches(
            kind,
            bound_id,
            run_id=run_id,
            session_id=session_id,
            expect_kind=expect_kind,
        ):
            return None
    return profile_id


def commit_stream_ticket(
    ticket: str | None,
    run_id: str | None = None,
    *,
    session_id: str | None = None,
    expect_kind: str | None = None,
) -> str | None:
    """Consume one ticket use once the stream endpoint is ready to respond."""
    if not ticket:
        return None
    now = time.time()
    with _stream_tickets_lock:
        entry = _stream_tickets.get(ticket)
        if not entry:
            return None
        profile_id, expiry, uses_left, kind, bound_id = entry
        if expiry < now:
            _stream_tickets.pop(ticket, None)
            return None
        if not _ticket_matches(
            kind,
            bound_id,
            run_id=run_id,
            session_id=session_id,
            expect_kind=expect_kind,
        ):
            return None
        if uses_left <= 1:
            _stream_tickets.pop(ticket, None)
        else:
            _stream_tickets[ticket] = (profile_id, expiry, uses_left - 1, kind, bound_id)
    return profile_id


def consume_stream_ticket(ticket: str | None) -> str | None:
    """Legacy single-use consume for auth-provider SSE (no run binding)."""
    if not ticket:
        return None
    with _stream_tickets_lock:
        entry = _stream_tickets.pop(ticket, None)
    if not entry:
        return None
    profile_id, expiry, _uses_left, _kind, _bound = entry
    if expiry < time.time():
        return None
    return profile_id


def stream_ticket_from_handler(handler: SimpleHTTPRequestHandler) -> str | None:
    parsed = urlparse(handler.path)
    raw = (parse_qs(parsed.query).get("ticket") or [None])[0]
    if raw is None:
        return None
    return str(raw).strip() or None
