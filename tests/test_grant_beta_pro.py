"""Tests for scripts/grant_beta_pro.py (hosted Pro bulk grant)."""

from __future__ import annotations

import scripts.grant_beta_pro as grant


def test_main_dry_run_lists_users(monkeypatch, capsys) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://demo.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")

    def fake_list(_base: str, _key: str) -> list[dict]:
        return [
            {
                "id": "11111111-1111-4111-8111-111111111111",
                "email": "beta@example.com",
                "app_metadata": {"plan": "free"},
                "created_at": "2026-01-01T00:00:00Z",
            }
        ]

    monkeypatch.setattr(grant, "list_users", fake_list)
    monkeypatch.setattr(
        grant,
        "admin_request",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not write")),
    )

    rc = grant.main(["--email", "beta@example.com"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "DRY-RUN" in out
    assert "beta@example.com" in out
    assert "'free' -> 'pro'" in out


def test_main_apply_updates_user(monkeypatch, capsys) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://demo.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")
    writes: list[tuple] = []

    def fake_list(_base: str, _key: str) -> list[dict]:
        return [
            {
                "id": "11111111-1111-4111-8111-111111111111",
                "email": "beta@example.com",
                "app_metadata": {"plan": "free", "beta": True},
                "created_at": "2026-01-01T00:00:00Z",
            }
        ]

    def fake_request(method, url, *, key, body=None):
        writes.append((method, url, body))
        return {}

    monkeypatch.setattr(grant, "list_users", fake_list)
    monkeypatch.setattr(grant, "admin_request", fake_request)

    rc = grant.main(["--email", "beta@example.com", "--apply"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "APPLY" in out
    assert len(writes) == 1
    assert writes[0][0] == "PUT"
    assert writes[0][2]["app_metadata"]["plan"] == "pro"
    assert writes[0][2]["app_metadata"]["beta"] is True
