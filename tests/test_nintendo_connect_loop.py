import auth.runner as runner


class _FakeTime:
    def __init__(self, step_s=1.0):
        self.t = 0.0
        self.step_s = step_s

    def time(self):
        self.t += self.step_s
        return self.t


class _FakeCookie:
    def __init__(self, name, value, domain):
        self.name = name
        self.value = value
        self.domain = domain


class _FakePage:
    def __init__(self, url="about:blank"):
        self.url = url
        self.is_closed = False
        self.goto_calls = 0

    def goto(self, url, *, wait_until=None, timeout=None):
        self.goto_calls += 1
        self.url = url

    def bring_to_front(self):
        return None

    def wait_for_timeout(self, _ms):
        return None


class _FakeContext:
    def __init__(self, pages, cookies=None):
        self.pages = pages
        self._cookies = cookies or []

    def new_page(self):
        page = _FakePage()
        self.pages.append(page)
        return page

    def cookies(self):
        return list(self._cookies)


def test_nintendo_connect_drives_non_blank_tab(monkeypatch):
    clock = _FakeTime(step_s=5.0)
    monkeypatch.setattr(runner, "time", clock)
    blank = _FakePage("about:blank")
    login = _FakePage("https://accounts.nintendo.com/")
    eshop = _FakePage("https://ec.nintendo.com/my/transactions/")
    ctx = _FakeContext(
        [blank, login],
        cookies=[
            {"name": "NASID", "value": "abc", "domain": "ec.nintendo.com"},
            {"name": "idToken", "value": "tok", "domain": "ec.nintendo.com"},
        ],
    )

    def _goto(url, *, wait_until=None, timeout=None):
        login.goto_calls += 1
        if "ec.nintendo.com" in url:
            login.url = eshop.url
        else:
            login.url = url

    login.goto = _goto
    monkeypatch.setattr("auth.connect_extractors.nintendo_has_session", lambda _ctx: True)
    monkeypatch.setattr("auth.connect_extractors.nintendo_session_has_id_token", lambda _ctx: True)
    monkeypatch.setattr("auth.connect_extractors._cookie_header", lambda _cookies, _domains: "NASID=abc; idToken=tok")
    creds = runner._extract_nintendo_inline(login, ctx, session=None)
    assert creds == {"NINTENDO_COOKIE": "NASID=abc; idToken=tok"}
    assert login.goto_calls >= 1
