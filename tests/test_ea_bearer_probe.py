from unittest.mock import MagicMock

from auth.connect_extractors import HeaderSniffer, extract_ea_bearer_session
from clients.ea_session import EA_GRAPHQL_HOST, normalize_bearer


def test_extract_ea_accepts_sniffed_bearer_when_apq_stale(monkeypatch):
    monkeypatch.setattr(
        "clients.ea_session.probe_ea_token",
        lambda _t, _c: {"ok": False, "error": "EA GraphQL HTTP 400: PersistedQueryNotFound"},
    )
    sniffer = HeaderSniffer(
        url_substr=EA_GRAPHQL_HOST, fields={"authorization": "EA_BEARER_TOKEN"}, normalize=normalize_bearer
    )
    sniffer.captured["EA_BEARER_TOKEN"] = "live-token"
    ctx = MagicMock()
    ctx.cookies.return_value = []
    creds = extract_ea_bearer_session(ctx, sniffer=sniffer)
    assert creds == {"EA_PROFILE": "ready", "EA_BEARER_TOKEN": "live-token"}
