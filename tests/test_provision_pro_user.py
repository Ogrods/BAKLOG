"""Tests for scripts/provision_pro_user.py."""

from __future__ import annotations

import scripts.provision_pro_user as provision


def test_provision_dry_run_new_user(monkeypatch, capsys) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://demo.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")
    monkeypatch.setattr(provision, "find_user_by_email", lambda *_a, **_k: None)

    rc = provision.main(["--email", "new@example.com"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "DRY-RUN" in out
    assert "create + plan=pro" in out


def test_provision_apply_creates_user(monkeypatch, capsys) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://demo.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")
    calls: list[tuple] = []

    def fake_create(base, key, email, *, plan, email_confirm):
        calls.append((email, plan, email_confirm))
        return {"id": "11111111-1111-4111-8111-111111111111", "email": email}

    monkeypatch.setattr(provision, "find_user_by_email", lambda *_a, **_k: None)
    monkeypatch.setattr(provision, "create_user_by_email", fake_create)

    rc = provision.main(["--email", "new@example.com", "--apply"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "created" in out
    assert calls == [("new@example.com", "pro", True)]


def test_provision_existing_upgrades(monkeypatch, capsys) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://demo.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")
    existing = {"id": "uid-1", "email": "beta@example.com", "app_metadata": {"plan": "free"}}
    writes: list[tuple] = []

    monkeypatch.setattr(provision, "find_user_by_email", lambda *_a, **_k: existing)
    monkeypatch.setattr(provision, "set_user_plan", lambda *a: writes.append(a))

    rc = provision.main(["--email", "beta@example.com", "--apply"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "upgrade -> pro" in out
    assert writes


def test_provision_from_invitees(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://demo.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")
    pro_file = tmp_path / "pro_invitees.txt"
    pro_file.write_text("paid@example.com\n", encoding="utf-8")
    monkeypatch.setattr("shared.comp_pro.COMP_PRO_EMAILS_PATH", pro_file)
    monkeypatch.setattr(provision, "find_user_by_email", lambda *_a, **_k: None)

    rc = provision.main(["--from-invitees"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "paid@example.com" in out


def test_provision_delete_requires_apply(monkeypatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://demo.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")
    rc = provision.main(["--email", "gone@example.com", "--delete"])
    assert rc == 2


def test_provision_delete_user(monkeypatch, capsys) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://demo.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")
    deleted: list[str] = []

    monkeypatch.setattr(
        provision,
        "delete_user_by_email",
        lambda _b, _k, email: deleted.append(email) or True,
    )

    rc = provision.main(["--email", "gone@example.com", "--delete", "--apply"])
    out = capsys.readouterr().out
    assert rc == 0
    assert deleted == ["gone@example.com"]
    assert "deleted" in out
