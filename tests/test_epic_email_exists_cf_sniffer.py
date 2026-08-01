"""Tests for Epic /id/api/email/exists Cloudflare challenge sniffer."""

from __future__ import annotations

from auth.connect_extractors import EpicEmailExistsCfSniffer


class _FakeResponse:
    def __init__(self, url: str, body: str, status: int = 403) -> None:
        self.url = url
        self.status = status
        self._body = body

    def text(self) -> str:
        return self._body


class _FakePage:
    def __init__(self) -> None:
        self._handlers: list = []

    def on(self, event: str, callback) -> None:
        if event == "response":
            self._handlers.append(callback)

    def emit(self, response: _FakeResponse) -> None:
        for cb in self._handlers:
            cb(response)


def test_sniffer_drains_challenge_url_from_non_200_html() -> None:
    token = "tok-abc-123"
    body = (
        "Enable JavaScript and cookies to continue"
        f'window._cf_chl_opt={{cUPMDTk:"/id/api/email/exists?__cf_chl_tk={token}"}}'
    )
    page = _FakePage()
    sniffer = EpicEmailExistsCfSniffer()
    sniffer.attach(page)
    page.emit(
        _FakeResponse(
            "https://www.epicgames.com/id/api/email/exists",
            body,
            status=403,
        )
    )
    url = sniffer.drain_challenge_url()
    assert url == f"https://www.epicgames.com/id/api/email/exists?__cf_chl_tk={token}"
    assert sniffer.drain_challenge_url() is None


def test_sniffer_ignores_normal_json_exists_response() -> None:
    page = _FakePage()
    sniffer = EpicEmailExistsCfSniffer()
    sniffer.attach(page)
    page.emit(
        _FakeResponse(
            "https://www.epicgames.com/id/api/email/exists",
            '{"exists":false}',
            status=200,
        )
    )
    assert sniffer.drain_challenge_url() is None


def test_sniffer_ignores_unrelated_urls() -> None:
    page = _FakePage()
    sniffer = EpicEmailExistsCfSniffer()
    sniffer.attach(page)
    page.emit(
        _FakeResponse(
            "https://www.epicgames.com/id/api/redirect",
            "Enable JavaScript and cookies to continue _cf_chl_opt",
            status=403,
        )
    )
    assert sniffer.drain_challenge_url() is None
