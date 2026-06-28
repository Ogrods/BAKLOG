from __future__ import annotations
import server

def test_redact_log_line_scrubs_bearer() -> None:
    line = 'Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.xxx'
    assert '[redacted]' in server._redact_log_line(line)
    assert 'eyJhbGci' not in server._redact_log_line(line)

def test_redact_log_line_scrubs_npsso_and_refresh_token() -> None:
    line = 'NPSSO=abc123.secret NPSSO: token refresh_token=rt_abc'
    out = server._redact_log_line(line)
    assert 'abc123' not in out
    assert 'rt_abc' not in out
    assert '[redacted]' in out

def test_redact_log_line_scrubs_set_cookie_and_non_bearer_auth() -> None:
    line = 'set-cookie: session=secret; path=/ Authorization: Ubi_v1 abcdef'
    out = server._redact_log_line(line)
    assert 'session=secret' not in out
    assert 'abcdef' not in out
    assert '[redacted]' in out

def test_redact_cookie_value_runs_to_end_of_line() -> None:
    line = 'Cookie: a=1; b=two three; sessionid=topsecretvalue'
    out = server._redact_log_line(line)
    assert 'topsecretvalue' not in out
    assert 'two three' not in out
    assert '[redacted]' in out

def test_redact_log_line_scrubs_passphrase() -> None:
    for line in ('passphrase="hunter2longphrase"', 'passphrase=hunter2longphrase'):
        out = server._redact_log_line(line)
        assert 'hunter2longphrase' not in out
        assert '[redacted]' in out

def test_redact_log_line_scrubs_per_store_tokens() -> None:
    line = 'GOG_AL=gogvalue123 EPIC_AUTH_CODE=epiccode456 EA_BEARER_TOKEN=eatoken789 XBL_API_KEY=xblkey000 UBISOFT_SESSION_ID=ubisess111 STEAM_API_KEY=steamkey222'
    out = server._redact_log_line(line)
    for secret in ('gogvalue123', 'epiccode456', 'eatoken789', 'xblkey000', 'ubisess111', 'steamkey222'):
        assert secret not in out
    assert '[redacted]' in out