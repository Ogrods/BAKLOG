"""Run log line redaction for secrets in fetcher output."""

from __future__ import annotations

import server


def test_redact_log_line_scrubs_bearer() -> None:
    line = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.xxx"
    assert "[redacted]" in server._redact_log_line(line)
    assert "eyJhbGci" not in server._redact_log_line(line)


def test_redact_log_line_scrubs_npsso_and_refresh_token() -> None:
    line = "NPSSO=abc123.secret NPSSO: token refresh_token=rt_abc"
    out = server._redact_log_line(line)
    assert "abc123" not in out
    assert "rt_abc" not in out
    assert "[redacted]" in out


def test_redact_log_line_scrubs_set_cookie_and_non_bearer_auth() -> None:
    line = "set-cookie: session=secret; path=/ Authorization: Ubi_v1 abcdef"
    out = server._redact_log_line(line)
    assert "session=secret" not in out
    assert "abcdef" not in out
    assert "[redacted]" in out
