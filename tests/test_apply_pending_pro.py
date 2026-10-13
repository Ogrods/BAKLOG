"""Tests for scripts/apply_pending_pro.py (different-email Polar buyers)."""

from __future__ import annotations

import scripts.apply_pending_pro as link


def _setup(monkeypatch, *, pending: dict | None, user: dict | None) -> list[tuple]:
    monkeypatch.setenv("SUPABASE_URL", "https://demo.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")
    writes: list[tuple] = []

    def fake_request(method, url, *, key, body=None):
        if method == "GET":
            return [pending] if pending else []
        writes.append((method, url, body))
        return {}

    monkeypatch.setattr(link, "admin_request", fake_request)
    monkeypatch.setattr(link, "find_user_by_email", lambda _u, _k, _e: user)
    return writes


ACCOUNT = {"id": "u1", "email": "account@example.com", "app_metadata": {"plan": "pro", "comp_until": "2027-03-31"}}
PENDING = {"email": "buyer@example.com", "plan": "pro", "applied_at": None}


def test_paid_pro_metadata_keeps_existing_paid_since() -> None:
    meta = link.paid_pro_metadata({"plan": "pro", "paid": True, "paid_since": "2027-01-01"}, "2027-02-01")
    assert meta["paid_since"] == "2027-01-01"
    fresh = link.paid_pro_metadata({"plan": "free", "comp_until": "2027-03-31"}, "2027-02-01")
    assert fresh == {"plan": "pro", "paid": True, "paid_since": "2027-02-01", "comp_until": "2027-03-31"}


def test_dry_run_does_not_write(monkeypatch, capsys) -> None:
    writes = _setup(monkeypatch, pending=PENDING, user=ACCOUNT)
    assert link.main(["--email", "buyer@example.com", "--to", "account@example.com"]) == 0
    assert writes == []
    assert "DRY-RUN" in capsys.readouterr().out


def test_apply_marks_account_paid_and_pending_applied(monkeypatch) -> None:
    writes = _setup(monkeypatch, pending=PENDING, user=ACCOUNT)
    assert link.main(["--email", "Buyer@Example.com", "--to", "account@example.com", "--apply"]) == 0
    put, patch = writes
    assert put[0] == "PUT" and put[1].endswith("/u1")
    assert put[2]["app_metadata"]["paid"] is True
    assert put[2]["app_metadata"]["comp_until"] == "2027-03-31"
    assert patch[0] == "PATCH" and "buyer%40example.com" in patch[1]
    assert patch[2]["applied_user_id"] == "u1"


def test_refuses_without_pending_unless_forced(monkeypatch) -> None:
    writes = _setup(monkeypatch, pending=None, user=ACCOUNT)
    assert link.main(["--email", "x@example.com", "--to", "account@example.com", "--apply"]) == 1
    assert link.main(["--email", "x@example.com", "--to", "account@example.com", "--apply", "--force"]) == 0
    assert [w[0] for w in writes] == ["PUT"]


def test_refuses_cancelled_or_applied_rows(monkeypatch) -> None:
    for pending in (
        {"email": "b@example.com", "plan": "free", "applied_at": None},
        {"email": "b@example.com", "plan": "pro", "applied_at": "2026-10-01T00:00:00Z"},
    ):
        writes = _setup(monkeypatch, pending=pending, user=ACCOUNT)
        assert link.main(["--email", "b@example.com", "--to", "account@example.com", "--apply"]) == 1
        assert writes == []
