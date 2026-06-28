import json
from unittest.mock import MagicMock

import pytest

from shared import polar_license as pl


@pytest.fixture(autouse=True)
def _polar_env(monkeypatch):
    monkeypatch.setenv("BAKLOG_POLAR_ORG_ID", "00000000-0000-4000-8000-000000000001")
    monkeypatch.setenv("BAKLOG_POLAR_API_BASE", "https://api.polar.sh")


def test_polar_configured_requires_org_id(monkeypatch):
    monkeypatch.delenv("BAKLOG_POLAR_ORG_ID", raising=False)
    assert pl.polar_configured() is False


def test_validate_license_key_granted(monkeypatch):
    payload = json.dumps({"status": "granted", "key": "BAKLOG-TEST"}).encode()

    def fake_urlopen(req, timeout=0):
        assert req.full_url.endswith("/v1/customer-portal/license-keys/validate")
        body = json.loads(req.data.decode())
        assert body["organization_id"] == "00000000-0000-4000-8000-000000000001"
        assert body["key"] == "BAKLOG-TEST"
        resp = MagicMock()
        resp.read.return_value = payload
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    out = pl.validate_license_key("BAKLOG-TEST")
    assert out["ok"] is True
    assert out["status"] == "granted"


def test_validate_license_key_revoked(monkeypatch):
    payload = json.dumps({"status": "revoked"}).encode()

    def fake_urlopen(req, timeout=0):
        resp = MagicMock()
        resp.read.return_value = payload
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    out = pl.validate_license_key("BAKLOG-DEAD")
    assert out["ok"] is False
    assert "revoked" in (out.get("error") or "")


def test_validate_license_key_not_found(monkeypatch):
    import urllib.error

    err = urllib.error.HTTPError(
        url="https://api.polar.sh/v1/customer-portal/license-keys/validate",
        code=404,
        msg="Not Found",
        hdrs=None,
        fp=None,
    )

    def fake_urlopen(req, timeout=0):
        raise err

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    out = pl.validate_license_key("BAKLOG-MISSING")
    assert out["ok"] is False
    assert out["error"] == "License key not found"
