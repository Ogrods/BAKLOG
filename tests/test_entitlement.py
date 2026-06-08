"""Tests for plan/entitlement resolution."""

from __future__ import annotations

import json

import pytest

import shared.entitlement as ent
from shared.supabase_auth import _extract_plan


@pytest.fixture(autouse=True)
def _clean_env(tmp_path, monkeypatch):
    monkeypatch.delenv("BAKLOG_PLAN", raising=False)
    # Default to pure-local mode (no hosted auth) for the license tests.
    monkeypatch.delenv("BAKLOG_SUPABASE_URL", raising=False)
    monkeypatch.delenv("BAKLOG_SUPABASE_ANON_KEY", raising=False)
    monkeypatch.delenv("BAKLOG_AUTH_DISABLED", raising=False)
    # Point the license file somewhere empty by default.
    monkeypatch.setenv("BAKLOG_LICENSE_FILE", str(tmp_path / "license.json"))
    # Reset the process-level authenticated-plan cache between tests.
    monkeypatch.setattr(ent, "_LAST_AUTH_PLAN", None)


def _enable_auth(monkeypatch):
    monkeypatch.setenv("BAKLOG_SUPABASE_URL", "https://demo.supabase.co")
    monkeypatch.setenv("BAKLOG_SUPABASE_ANON_KEY", "anon-key")


def test_defaults_to_free():
    assert ent.current_plan() == "free"
    assert ent.is_pro() is False


@pytest.mark.parametrize("value", ["pro", "paid", "premium", "PRO"])
def test_env_override_pro(monkeypatch, value):
    monkeypatch.setenv("BAKLOG_PLAN", value)
    assert ent.current_plan() == "pro"
    assert ent.is_pro() is True


def test_env_override_free_wins_over_license(tmp_path, monkeypatch):
    (tmp_path / "license.json").write_text(json.dumps({"plan": "pro"}), encoding="utf-8")
    monkeypatch.setenv("BAKLOG_PLAN", "free")
    assert ent.current_plan() == "free"


def test_local_license_file_pro(tmp_path):
    license_path = ent.license_path()
    license_path.write_text(json.dumps({"plan": "pro"}), encoding="utf-8")
    assert ent.current_plan() == "pro"


def test_local_license_file_non_pro(tmp_path):
    ent.license_path().write_text(json.dumps({"plan": "free"}), encoding="utf-8")
    assert ent.current_plan() == "free"


def test_malformed_license_is_free(tmp_path):
    ent.license_path().write_text("not json", encoding="utf-8")
    assert ent.current_plan() == "free"


def test_extract_plan_trusts_only_server_controlled_claims():
    assert _extract_plan({"plan": "Pro"}) == "pro"
    assert _extract_plan({"app_metadata": {"plan": "premium"}}) == "premium"
    # user_metadata is self-editable by Supabase users -> must be ignored.
    assert _extract_plan({"user_metadata": {"plan": "pro"}}) is None
    assert _extract_plan({"sub": "abc"}) is None


def test_license_ignored_when_auth_enabled(monkeypatch):
    """A local license.json must not bypass the hosted entitlement moat."""
    ent.license_path().write_text(json.dumps({"plan": "pro"}), encoding="utf-8")
    _enable_auth(monkeypatch)
    assert ent.current_plan() == "free"  # no bearer
    assert ent.current_plan("Bearer not.a.real.token") == "free"  # invalid bearer


def test_jwt_plan_pro_when_auth_enabled(monkeypatch):
    _enable_auth(monkeypatch)
    monkeypatch.setattr("shared.supabase_auth.verify_bearer_plan", lambda auth: "pro")
    assert ent.current_plan("Bearer x") == "pro"
    assert ent.is_pro("Bearer x") is True


def test_jwt_free_claim_when_auth_enabled(monkeypatch):
    _enable_auth(monkeypatch)
    monkeypatch.setattr("shared.supabase_auth.verify_bearer_plan", lambda auth: "free")
    assert ent.current_plan("Bearer x") == "free"


def test_env_override_ignored_when_auth_enabled(monkeypatch):
    # BAKLOG_PLAN is a local-only override; under hosted auth it must NOT grant
    # pro (otherwise an env var would bypass the entitlement moat for all users).
    _enable_auth(monkeypatch)
    monkeypatch.setenv("BAKLOG_PLAN", "pro")
    assert ent.current_plan() == "free"  # no bearer -> free, env ignored


def test_background_plan_caches_last_authenticated(monkeypatch):
    _enable_auth(monkeypatch)
    monkeypatch.setattr("shared.supabase_auth.verify_bearer_plan", lambda auth: "pro")
    assert ent.is_pro_background() is False  # nothing verified yet
    ent.current_plan("Bearer x")  # caches a verified pro plan
    assert ent.is_pro_background() is True


def test_background_plan_pure_local_reads_license():
    ent.license_path().write_text(json.dumps({"plan": "pro"}), encoding="utf-8")
    assert ent.is_pro_background() is True


def test_background_plan_free_when_auth_enabled_uncached(monkeypatch):
    """Hosted auth with no verified session yet must not fall back to license."""
    ent.license_path().write_text(json.dumps({"plan": "pro"}), encoding="utf-8")
    _enable_auth(monkeypatch)
    assert ent.is_pro_background() is False
