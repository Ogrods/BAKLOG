"""Tests for shared/pro_capabilities.py."""

from __future__ import annotations

import pytest

from shared.pro_capabilities import (
    CAPABILITY_IDS,
    COMING_CAPABILITY_IDS,
    LIVE_CAPABILITY_IDS,
    capability_enabled,
    resolve_capabilities,
)

OPT_IN_LIVE_CAPABILITY_IDS = frozenset({"cloud_sync_mirror"})


@pytest.fixture(autouse=True)
def _no_auth(monkeypatch):
    monkeypatch.delenv("BAKLOG_SUPABASE_URL", raising=False)
    monkeypatch.delenv("BAKLOG_SUPABASE_ANON_KEY", raising=False)


def test_registry_ids_are_unique():
    assert len(CAPABILITY_IDS) == len(set(CAPABILITY_IDS))


def test_live_and_coming_are_disjoint():
    assert not LIVE_CAPABILITY_IDS & COMING_CAPABILITY_IDS


def test_free_plan_disables_live_capabilities():
    caps = resolve_capabilities(plan="free", pro_settings={})
    for cap_id in LIVE_CAPABILITY_IDS:
        assert caps[cap_id]["enabled"] is False
        assert caps[cap_id]["status"] == "live"


def test_pro_plan_enables_live_capabilities_without_opt_in():
    caps = resolve_capabilities(plan="pro", pro_settings={"cloudMirrorEnabled": False})
    for cap_id in LIVE_CAPABILITY_IDS - OPT_IN_LIVE_CAPABILITY_IDS:
        assert caps[cap_id]["enabled"] is True, cap_id


def test_coming_capabilities_never_enabled():
    caps = resolve_capabilities(plan="pro", pro_settings={"cloudMirrorEnabled": True})
    for cap_id in COMING_CAPABILITY_IDS:
        assert caps[cap_id]["enabled"] is False
        assert caps[cap_id]["status"] == "coming"


def test_cloud_mirror_requires_auth_and_opt_in_when_live(monkeypatch):
    off = resolve_capabilities(plan="pro", pro_settings={"cloudMirrorEnabled": False})
    assert off["cloud_sync_mirror"]["status"] == "live"
    assert off["cloud_sync_mirror"]["enabled"] is False

    monkeypatch.setenv("BAKLOG_SUPABASE_URL", "https://demo.supabase.co")
    monkeypatch.setenv("BAKLOG_SUPABASE_ANON_KEY", "anon")
    still_off = resolve_capabilities(plan="pro", pro_settings={"cloudMirrorEnabled": False})
    assert still_off["cloud_sync_mirror"]["enabled"] is False

    on = resolve_capabilities(plan="pro", pro_settings={"cloudMirrorEnabled": True})
    assert on["cloud_sync_mirror"]["enabled"] is True


def test_capability_enabled_helper():
    assert capability_enabled("queue_bulk_refresh", plan="pro", pro_settings={}) is True
    assert capability_enabled("queue_bulk_refresh", plan="free", pro_settings={}) is False
