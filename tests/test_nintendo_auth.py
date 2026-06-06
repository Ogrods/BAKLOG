"""Tests for Nintendo Connections session validation."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

from auth.runner import _nintendo_has_session, _nintendo_session_has_id_token


def test_nintendo_has_session_requires_named_cookies() -> None:
    class Ctx:
        @staticmethod
        def cookies():
            return [
                {"name": "tracking", "value": "x", "domain": "ec.nintendo.com"},
            ]

    assert _nintendo_has_session(Ctx()) is False

    class CtxOk:
        @staticmethod
        def cookies():
            return [
                {"name": "NASID", "value": "sess", "domain": "ec.nintendo.com"},
            ]

    assert _nintendo_has_session(CtxOk()) is True

    class CtxNextAuth:
        @staticmethod
        def cookies():
            return [
                {
                    "name": "__Secure-next-auth.session-token",
                    "value": "sess",
                    "domain": "ec.nintendo.com",
                },
            ]

    assert _nintendo_has_session(CtxNextAuth()) is True


def test_nintendo_session_has_id_token(monkeypatch) -> None:
    class Ctx:
        class request:
            @staticmethod
            def get(url: str, timeout: float = 30) -> MagicMock:
                _ = timeout
                resp = MagicMock()
                resp.status = 200
                resp.text = json.dumps({"idToken": "tok123"})
                return resp

    assert _nintendo_session_has_id_token(Ctx()) is True
