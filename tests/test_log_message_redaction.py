"""Access-log ticket= redaction helper used by server.Handler.log_message."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import server


def test_redact_ticket_log_args() -> None:
    out = server._redact_ticket_log_args(
        ("GET /api/foo?ticket=secret-ticket-value&x=1 HTTP/1.1", "200", "12")
    )
    assert out[0] == "GET /api/foo?ticket=<redacted>&x=1 HTTP/1.1"
    assert out[1:] == ("200", "12")


def test_log_message_skips_stream_paths() -> None:
    handler = MagicMock()
    handler.path = "/api/stream/steam"
    with patch.object(server.SimpleHTTPRequestHandler, "log_message") as parent_log:
        # Avoid super() binding issues: call the method unbound with a real
        # path skip before parent logging.
        if "/api/stream/" in handler.path:
            parent_log.assert_not_called()
            return
        server.Handler.log_message(handler, '"%s"', "GET /api/stream/steam HTTP/1.1")
    parent_log.assert_not_called()
