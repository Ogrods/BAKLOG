"""SSE stream tickets bind kind + session/run id."""

from __future__ import annotations

from shared.server_stream_tickets import (
    KIND_AUTH,
    KIND_RUN,
    commit_stream_ticket,
    mint_stream_ticket,
    peek_stream_ticket,
)


def test_run_ticket_rejected_on_auth_stream() -> None:
    ticket = mint_stream_ticket("default", run_id="run-1")
    assert peek_stream_ticket(ticket, session_id="sess-a", expect_kind=KIND_AUTH) is None
    assert commit_stream_ticket(ticket, session_id="sess-a", expect_kind=KIND_AUTH) is None
    assert peek_stream_ticket(ticket, "run-1", expect_kind=KIND_RUN) == "default"


def test_auth_ticket_bound_to_session() -> None:
    ticket = mint_stream_ticket("default", session_id="sess-a")
    assert peek_stream_ticket(ticket, session_id="sess-a", expect_kind=KIND_AUTH) == "default"
    assert peek_stream_ticket(ticket, session_id="sess-b", expect_kind=KIND_AUTH) is None
    assert peek_stream_ticket(ticket, "run-1", expect_kind=KIND_RUN) is None


def test_auth_ticket_commit_session_mismatch() -> None:
    ticket = mint_stream_ticket("default", session_id="sess-a")
    assert commit_stream_ticket(ticket, session_id="sess-b", expect_kind=KIND_AUTH) is None
    assert commit_stream_ticket(ticket, session_id="sess-a", expect_kind=KIND_AUTH) == "default"
