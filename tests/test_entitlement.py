"""Tests for plan/entitlement resolution."""

from __future__ import annotations

import json

import pytest

import shared.entitlement as ent
from shared.supabase_auth import _extract_plan


@pytest.fixture(autouse=True)
def _clean_env(tmp_path, monkeypatch):
    monkeypatch.delenv("BAKLOG_PLAN", raising=False)
    # Point the license file somewhere empty by default.
    monkeypatch.setenv("BAKLOG_LICENSE_FILE", str(tmp_path / "license.json"))


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


def test_extract_plan_reads_top_level_and_metadata():
    assert _extract_plan({"plan": "Pro"}) == "pro"
    assert _extract_plan({"app_metadata": {"plan": "premium"}}) == "premium"
    assert _extract_plan({"user_metadata": {"plan": "pro"}}) == "pro"
    assert _extract_plan({"sub": "abc"}) is None
