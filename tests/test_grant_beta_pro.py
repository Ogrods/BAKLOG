"""Tests for scripts/grant_beta_pro.py (hosted Pro bulk grant)."""

from __future__ import annotations

from datetime import date

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


def _patch_users(monkeypatch, users: list[dict]) -> list[tuple]:
    monkeypatch.setenv("SUPABASE_URL", "https://demo.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")
    writes: list[tuple] = []

    def fake_request(method, url, *, key, body=None):
        writes.append((method, url, body))
        return {}

    monkeypatch.setattr(grant, "list_users", lambda _b, _k: users)
    monkeypatch.setattr(grant, "admin_request", fake_request)
    monkeypatch.setattr(grant, "_today", lambda: date(2027, 4, 1))
    return writes


def _user(uid: str, email: str, meta: dict) -> dict:
    return {"id": uid, "email": email, "app_metadata": meta, "created_at": "2026-01-01T00:00:00Z"}


def test_until_writes_comp_until(monkeypatch) -> None:
    writes = _patch_users(monkeypatch, [_user("u1", "beta@example.com", {"plan": "free"})])
    rc = grant.main(["--email", "beta@example.com", "--until", "2027-05-31", "--apply"])
    assert rc == 0
    meta = writes[0][2]["app_metadata"]
    assert meta == {"plan": "pro", "comp_until": "2027-05-31"}


def test_until_rejected_with_free_plan(monkeypatch) -> None:
    writes = _patch_users(monkeypatch, [_user("u1", "beta@example.com", {"plan": "pro"})])
    assert grant.main(["--plan", "free", "--until", "2027-05-31", "--apply"]) == 2
    assert grant.main(["--until", "not-a-date", "--apply"]) == 2
    assert writes == []


def test_expire_only_touches_past_comp_until(monkeypatch, capsys) -> None:
    users = [
        _user("u1", "cohort@example.com", {"plan": "pro", "comp_until": "2027-03-31"}),
        _user("u2", "paul@example.com", {"plan": "pro", "comp_until": "2027-05-31"}),
        _user("u3", "payer@example.com", {"plan": "pro"}),
        _user("u4", "free@example.com", {"plan": "free"}),
        _user("u5", "paid-tester@example.com", {"plan": "pro", "paid": True, "comp_until": "2027-03-31"}),
    ]
    writes = _patch_users(monkeypatch, users)
    rc = grant.main(["--expire", "--apply"])
    out = capsys.readouterr().out
    assert rc == 0
    assert len(writes) == 1
    assert writes[0][1].endswith("/u1")
    # GoTrue merges app_metadata on PUT; None (JSON null) is what removes comp_until.
    assert writes[0][2]["app_metadata"] == {"plan": "free", "comp_until": None}
    assert "paul@example.com" not in out
    assert "payer@example.com" not in out
    assert "paid-tester@example.com" not in out


def test_skip_pro_and_exclude(monkeypatch) -> None:
    users = [
        _user("u1", "owner@example.com", {"plan": "pro"}),
        _user("u2", "tester@example.com", {"plan": "free"}),
        _user("u3", "Skip.Me@example.com", {"plan": "free"}),
        _user("u4", "other@example.com", {}),
    ]
    writes = _patch_users(monkeypatch, users)
    rc = grant.main(
        ["--until", "2027-03-31", "--skip-pro", "--exclude", "skip.me@EXAMPLE.com", "--apply"]
    )
    assert rc == 0
    assert sorted(w[1].rsplit("/", 1)[-1] for w in writes) == ["u2", "u4"]
    assert all(w[2]["app_metadata"]["comp_until"] == "2027-03-31" for w in writes)


def test_expire_dry_run_does_not_write(monkeypatch) -> None:
    writes = _patch_users(
        monkeypatch, [_user("u1", "cohort@example.com", {"plan": "pro", "comp_until": "2027-03-31"})]
    )
    assert grant.main(["--expire"]) == 0
    assert writes == []
