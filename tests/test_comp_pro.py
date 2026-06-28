"""Tests for shared.comp_pro (auto Pro on sign-in)."""

from __future__ import annotations

from shared import comp_pro


def test_load_comp_pro_emails(tmp_path) -> None:
    path = tmp_path / "list.txt"
    path.write_text("# comment\n\nPAUL@example.com\n", encoding="utf-8")
    assert comp_pro.load_comp_pro_emails(path) == frozenset({"paul@example.com"})


def test_ensure_comp_pro_skips_unlisted(monkeypatch) -> None:
    monkeypatch.setattr(comp_pro, "load_comp_pro_emails", lambda *_a, **_k: frozenset({"listed@example.com"}))
    assert comp_pro.ensure_comp_pro_on_login("uid", "other@example.com") == (False, False)


def test_ensure_comp_pro_upgrades(monkeypatch) -> None:
    monkeypatch.setattr(comp_pro, "load_comp_pro_emails", lambda *_a, **_k: frozenset({"paul@example.com"}))
    monkeypatch.setattr(comp_pro, "_admin_creds", lambda: ("https://demo.supabase.co", "service-key"))
    writes: list[tuple] = []

    def fake_admin(method, url, *, key, body=None):
        if method == "GET":
            return {"id": "uid-1", "app_metadata": {"plan": "free"}}
        writes.append((method, url, body))
        return {"id": "uid-1", "app_metadata": body.get("app_metadata") if body else {}}

    monkeypatch.setattr(comp_pro, "admin_request", fake_admin)
    should, upgraded = comp_pro.ensure_comp_pro_on_login("uid-1", "paul@example.com")
    assert should is True
    assert upgraded is True
    assert writes and writes[0][2]["app_metadata"]["plan"] == "pro"


def test_ensure_comp_pro_idempotent_when_already_pro(monkeypatch) -> None:
    monkeypatch.setattr(comp_pro, "load_comp_pro_emails", lambda *_a, **_k: frozenset({"paul@example.com"}))
    monkeypatch.setattr(comp_pro, "_admin_creds", lambda: ("https://demo.supabase.co", "service-key"))
    calls: list[str] = []

    def fake_admin(method, url, *, key, body=None):
        calls.append(method)
        return {"id": "uid-1", "app_metadata": {"plan": "pro"}}

    monkeypatch.setattr(comp_pro, "admin_request", fake_admin)
    should, upgraded = comp_pro.ensure_comp_pro_on_login("uid-1", "paul@example.com")
    assert should is True
    assert upgraded is False
    assert calls == ["GET"]
