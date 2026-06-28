"""Connect tab selection when CDP lists a blank popup before the login tab."""

from __future__ import annotations

from auth.runner import _connect_pages, _drive_connect_page


class _FakePage:
    def __init__(self, url: str = "about:blank", *, closed: bool = False) -> None:
        self.url = url
        self.is_closed = closed


class _FakeContext:
    def __init__(self, pages: list[_FakePage]) -> None:
        self.pages = pages

    def new_page(self) -> _FakePage:
        page = _FakePage()
        self.pages.append(page)
        return page


def test_drive_connect_page_skips_leading_blank_popup() -> None:
    blank = _FakePage("about:blank")
    login = _FakePage("https://www.epicgames.com/id/login")
    ctx = _FakeContext([blank, login])
    assert _drive_connect_page(login, ctx) is login


def test_drive_connect_page_uses_primary_when_only_blank() -> None:
    blank = _FakePage("about:blank")
    ctx = _FakeContext([blank])
    assert _drive_connect_page(blank, ctx) is blank


def test_connect_pages_primary_first() -> None:
    blank = _FakePage("about:blank")
    login = _FakePage("https://ec.nintendo.com/my/transactions/")
    ctx = _FakeContext([blank, login])
    pages = _connect_pages(login, ctx)
    assert pages[0] is login
    assert blank in pages[1:]
