"""shared.http_error_snippet never dumps raw HTML into fetcher logs."""

from __future__ import annotations

from types import SimpleNamespace

from shared.http_error_snippet import http_error_snippet


def _resp(*, status: int, text: str, content_type: str = "text/plain") -> SimpleNamespace:
    return SimpleNamespace(
        status_code=status,
        text=text,
        headers={"Content-Type": content_type},
    )


def test_plain_text_snippet() -> None:
    out = http_error_snippet(_resp(status=502, text="bad gateway upstream"))
    assert out == "HTTP 502: bad gateway upstream"


def test_html_content_type_sanitized() -> None:
    html = "<!doctype html><html><head><title>Attention Required!</title></head><body>cf</body></html>"
    out = http_error_snippet(_resp(status=403, text=html, content_type="text/html; charset=utf-8"))
    assert "HTML error page from host" in out
    assert "Attention Required!" in out
    assert "<!doctype" not in out.lower()


def test_html_body_without_content_type() -> None:
    html = "<html><title>Gateway Timeout</title><body>oops</body></html>"
    out = http_error_snippet(_resp(status=504, text=html, content_type="application/octet-stream"))
    assert out.startswith("HTTP 504 (HTML error page from host)")
    assert "Gateway Timeout" in out
