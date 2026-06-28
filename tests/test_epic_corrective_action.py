import json

import pytest

import auth.runner as runner
from clients.epic_client import (
    EpicAuthError,
    EpicClient,
    EpicCorrectiveActionError,
    corrective_action_in_text,
    epic_error_fields,
    is_corrective_action,
)

CORRECTIVE_PAYLOAD = {
    "errorCode": "errors.com.epicgames.oauth.corrective_action_required",
    "message": "Corrective action is required to continue.",
    "metadata": {"correctiveAction": "PRIVACY_POLICY_ACCEPTANCE", "continuation": "continuation-token-123"},
    "correlationId": "abc-correlation",
}
INVALID_GRANT_PAYLOAD = {
    "errorCode": "errors.com.epicgames.account.oauth.invalid_grant",
    "message": "Sorry the originating session for the exchange code was not found.",
}


class _FakeResp:
    def __init__(self, status, payload=None, text=None):
        self.status_code = status
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload) if payload else ""

    def json(self):
        if self._payload is None:
            raise json.JSONDecodeError("no json", self.text or "", 0)
        return self._payload


def _client(tmp_path, resp):
    client = EpicClient(cache_dir=tmp_path)
    client.session.post = lambda *a, **k: resp
    return client


def test_epic_error_fields_parses_corrective_json():
    fields = epic_error_fields(json.dumps(CORRECTIVE_PAYLOAD))
    assert fields["errorCode"] == CORRECTIVE_PAYLOAD["errorCode"]
    assert fields["correctiveAction"] == "PRIVACY_POLICY_ACCEPTANCE"
    assert fields["continuation"] == "continuation-token-123"
    assert is_corrective_action(fields)


def test_epic_error_fields_handles_html_wrapped_json():
    wrapped = "<html><body><pre>" + json.dumps(CORRECTIVE_PAYLOAD) + "</pre></body></html>"
    fields = epic_error_fields(wrapped)
    assert fields["correctiveAction"] == "PRIVACY_POLICY_ACCEPTANCE"
    assert is_corrective_action(fields)
    assert corrective_action_in_text(wrapped) is not None


def test_invalid_grant_is_not_corrective():
    fields = epic_error_fields(json.dumps(INVALID_GRANT_PAYLOAD))
    assert not is_corrective_action(fields)
    assert corrective_action_in_text(json.dumps(INVALID_GRANT_PAYLOAD)) is None


def test_request_token_raises_corrective_action(tmp_path):
    client = _client(tmp_path, _FakeResp(400, CORRECTIVE_PAYLOAD))
    with pytest.raises(EpicCorrectiveActionError) as ei:
        client._request_token({"grant_type": "authorization_code", "code": "x"})
    err = ei.value
    assert err.corrective_action == "PRIVACY_POLICY_ACCEPTANCE"
    assert err.continuation == "continuation-token-123"
    assert "corrective_action_required" in (err.error_code or "")
    assert "privacy policy" in str(err).lower()


def test_request_token_generic_invalid_grant(tmp_path):
    client = _client(tmp_path, _FakeResp(400, INVALID_GRANT_PAYLOAD))
    with pytest.raises(EpicAuthError) as ei:
        client._request_token({"grant_type": "authorization_code", "code": "x"})
    assert not isinstance(ei.value, EpicCorrectiveActionError)
    assert "invalid_grant" in str(ei.value)


def test_request_token_corrective_in_html_body(tmp_path):
    wrapped = "<html><body>" + json.dumps(CORRECTIVE_PAYLOAD) + "</body></html>"
    client = _client(tmp_path, _FakeResp(400, payload=None, text=wrapped))
    with pytest.raises(EpicCorrectiveActionError):
        client._request_token({"grant_type": "authorization_code", "code": "x"})


def test_runner_helper_detects_corrective_body():
    assert runner._epic_error_from_text(json.dumps(CORRECTIVE_PAYLOAD)) is not None
    assert runner._epic_error_from_text(json.dumps({"authorizationCode": "abc123def456"})) is None
    assert runner._epic_error_from_text("") is None


def test_login_refresh_reraises_corrective_action(tmp_path, monkeypatch):
    client = EpicClient(cache_dir=tmp_path, auth_code="unused")
    client._load_session = lambda: {"refresh_token": "rtok"}
    client._request_token = lambda _data: (_ for _ in ()).throw(
        EpicCorrectiveActionError(
            "Epic privacy policy acceptance required", corrective_action="PRIVACY_POLICY_ACCEPTANCE"
        )
    )
    with pytest.raises(EpicCorrectiveActionError):
        client.login()
