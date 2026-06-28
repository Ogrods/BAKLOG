import json

import auth.runner as runner


class _FakeTime:
    def __init__(self, step_s=1.0):
        self.t = 0.0
        self.step_s = step_s

    def time(self):
        self.t += self.step_s
        return self.t


class _FakePage:
    def __init__(self, url="about:blank"):
        self.url = url
        self.is_closed = False
        self.goto_calls = 0

    def goto(self, _url, *, wait_until=None, timeout=None):
        self.goto_calls += 1
        if "id/login" in _url:
            self.url = _url

    def evaluate(self, _fn):
        return ""

    def content(self):
        if runner.EPIC_REDIRECT_MARKER in (self.url or ""):
            return json.dumps({"authorizationCode": "epic-lib-code-123"})
        return ""

    def wait_for_timeout(self, _ms):
        return None


class _FakeContext:
    def __init__(self, pages):
        self.pages = pages

    def new_page(self):
        page = _FakePage()
        self.pages.append(page)
        return page


def test_epic_library_captures_redirect_on_non_first_tab(monkeypatch):
    clock = _FakeTime()
    monkeypatch.setattr(runner, "time", clock)
    blank = _FakePage("about:blank")
    redirect = _FakePage("https://www.epicgames.com/id/api/redirect?clientId=x&responseType=code")
    ctx = _FakeContext([blank, redirect])
    primary = _FakePage("https://www.epicgames.com/id/login")
    ctx.pages.insert(1, primary)

    class _FakeEpicClient:
        def __init__(self, *, auth_code, cache_dir):
            assert auth_code == "epic-lib-code-123"

        def login(self):
            return None

    monkeypatch.setattr("clients.epic_client.EpicClient", _FakeEpicClient)
    monkeypatch.setattr("clients.epic_client.default_epic_cache_dir", lambda: "/tmp/epic")
    creds = runner._extract_epic_inline(primary, ctx, session=None)
    assert creds == {"EPIC_AUTH_CODE": "epic-lib-code-123"}
