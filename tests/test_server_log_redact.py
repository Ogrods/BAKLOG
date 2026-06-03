"""Run log line redaction for secrets in fetcher output."""

from __future__ import annotations

import server


def test_redact_log_line_scrubs_bearer() -> None:
    line = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.xxx"
    assert "[redacted]" in server._redact_log_line(line)
    assert "eyJhbGci" not in server._redact_log_line(line)
