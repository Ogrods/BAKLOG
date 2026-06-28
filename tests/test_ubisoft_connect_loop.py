from auth.connect_extractors import build_ubisoft_header_sniffer, extract_ubisoft_session, ubisoft_session_captured


class _FakeRequest:
    def __init__(self, url, headers):
        self.url = url
        self.headers = headers


class _FakeContext:
    def __init__(self):
        self._handlers = []

    def on(self, event, handler):
        if event == "request":
            self._handlers.append(handler)

    def emit_request(self, request):
        for handler in self._handlers:
            handler(request)


def test_ubisoft_header_sniffer_captures_api_headers():
    ctx = _FakeContext()
    sniffer = build_ubisoft_header_sniffer()
    sniffer.attach(ctx)
    ctx.emit_request(
        _FakeRequest(
            "https://public-ubiservices.ubi.com/v1/profiles/me/games",
            {"authorization": "Ubi_v1 t=abc", "ubi-sessionid": "sess-1", "ubi-appid": "app-1"},
        )
    )
    assert ubisoft_session_captured(sniffer) is True
    assert extract_ubisoft_session(sniffer) == {
        "UBISOFT_AUTH": "Ubi_v1 t=abc",
        "UBISOFT_SESSION_ID": "sess-1",
        "UBISOFT_APP_ID": "app-1",
    }


def test_ubisoft_header_sniffer_does_not_require_app_id():
    sniffer = build_ubisoft_header_sniffer()
    sniffer.captured = {"UBISOFT_AUTH": "x", "UBISOFT_SESSION_ID": "y"}
    assert extract_ubisoft_session(sniffer) == {"UBISOFT_AUTH": "x", "UBISOFT_SESSION_ID": "y"}
