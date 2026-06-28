import json
from unittest.mock import MagicMock

from auth.connect_extractors import nintendo_has_session, nintendo_session_has_id_token


def test_nintendo_has_session_requires_named_cookies():

    class Ctx:
        @staticmethod
        def cookies():
            return [{"name": "tracking", "value": "x", "domain": "ec.nintendo.com"}]

    assert nintendo_has_session(Ctx()) is False

    class CtxOk:
        @staticmethod
        def cookies():
            return [{"name": "NASID", "value": "sess", "domain": "ec.nintendo.com"}]

    assert nintendo_has_session(CtxOk()) is True

    class CtxNextAuth:
        @staticmethod
        def cookies():
            return [{"name": "__Secure-next-auth.session-token", "value": "sess", "domain": "ec.nintendo.com"}]

    assert nintendo_has_session(CtxNextAuth()) is True


def test_nintendo_session_has_id_token(monkeypatch):

    class Ctx:
        class request:
            @staticmethod
            def get(url, timeout=30):
                _ = timeout
                resp = MagicMock()
                resp.status = 200
                resp.text = json.dumps({"idToken": "tok123"})
                return resp

    assert nintendo_session_has_id_token(Ctx()) is True
