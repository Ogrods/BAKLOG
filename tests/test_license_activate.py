from __future__ import annotations
import json
import pytest
import shared.entitlement as ent

@pytest.fixture(autouse=True)
def _pure_local(tmp_path, monkeypatch):
    monkeypatch.delenv('BAKLOG_SUPABASE_URL', raising=False)
    monkeypatch.delenv('BAKLOG_SUPABASE_ANON_KEY', raising=False)
    monkeypatch.delenv('BAKLOG_PLAN', raising=False)
    monkeypatch.setenv('BAKLOG_LICENSE_FILE', str(tmp_path / 'license.json'))
    monkeypatch.setenv('BAKLOG_POLAR_ORG_ID', '00000000-0000-4000-8000-000000000001')
    monkeypatch.setattr(ent, '_LICENSE_REFRESH_AT', 0.0)

def test_activate_local_license_key_persists_pro(monkeypatch):
    monkeypatch.setattr('shared.polar_license.validate_license_key', lambda key: {'ok': True, 'status': 'granted', 'error': None})
    ok, msg = ent.activate_local_license_key('BAKLOG-AAAA-BBBB')
    assert ok is True
    assert 'activated' in msg.lower()
    doc = json.loads(ent.license_path().read_text(encoding='utf-8'))
    assert doc['plan'] == 'pro'
    assert doc['key'] == 'BAKLOG-AAAA-BBBB'
    assert ent.current_plan() == 'pro'

def test_activate_rejects_invalid_key(monkeypatch):
    monkeypatch.setattr('shared.polar_license.validate_license_key', lambda key: {'ok': False, 'status': 'revoked', 'error': 'License key is revoked'})
    ok, msg = ent.activate_local_license_key('BAKLOG-DEAD')
    assert ok is False
    assert 'revoked' in msg.lower()
    assert ent.current_plan() == 'free'

def test_activate_blocked_when_auth_enabled(monkeypatch):
    monkeypatch.setenv('BAKLOG_SUPABASE_URL', 'https://demo.supabase.co')
    monkeypatch.setenv('BAKLOG_SUPABASE_ANON_KEY', 'anon')
    ok, msg = ent.activate_local_license_key('BAKLOG-AAAA')
    assert ok is False
    assert 'local-only' in msg.lower()

def test_maybe_refresh_downgrades_revoked_key(monkeypatch, tmp_path):
    ent.write_license_document({'plan': 'pro', 'key': 'BAKLOG-OLD'})
    monkeypatch.setattr('shared.polar_license.validate_license_key', lambda key: {'ok': False, 'status': 'revoked', 'error': 'revoked'})
    ent.maybe_refresh_local_license(force=True)
    doc = json.loads(ent.license_path().read_text(encoding='utf-8'))
    assert doc['plan'] == 'free'
    assert ent.current_plan() == 'free'