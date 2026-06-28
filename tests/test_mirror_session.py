from __future__ import annotations
import time
import jwt
import pytest
from shared import entitlement as ent
from shared.mirror_session import clear_mirror_session_for_tests, get_mirror_session, note_authenticated_mirror_session
from shared.supabase_auth import reset_jwks_client_for_tests

@pytest.fixture(autouse=True)
def _reset_session():
    clear_mirror_session_for_tests()
    ent._LAST_AUTH_PLAN = None
    yield
    clear_mirror_session_for_tests()
    ent._LAST_AUTH_PLAN = None

@pytest.fixture()
def auth_env(monkeypatch):
    monkeypatch.setenv('BAKLOG_SUPABASE_URL', 'https://test.supabase.co')
    monkeypatch.setenv('BAKLOG_SUPABASE_ANON_KEY', 'anon-test')
    monkeypatch.setenv('BAKLOG_SUPABASE_JWT_SECRET', 'unit-test-secret')
    monkeypatch.delenv('BAKLOG_AUTH_DISABLED', raising=False)
    reset_jwks_client_for_tests()

def _pro_bearer(secret: str='unit-test-secret', sub: str='550e8400-e29b-41d4-a716-446655440000') -> str:
    token = jwt.encode({'sub': sub, 'aud': 'authenticated', 'iss': 'https://test.supabase.co/auth/v1', 'exp': int(time.time()) + 3600, 'app_metadata': {'plan': 'pro'}}, secret, algorithm='HS256')
    return f'Bearer {token}'

def test_note_and_get_mirror_session(auth_env):
    note_authenticated_mirror_session(_pro_bearer())
    session = get_mirror_session()
    assert session is not None
    user_id, token = session
    assert user_id == '550e8400-e29b-41d4-a716-446655440000'
    assert token

def test_current_plan_also_records_mirror_session(auth_env):
    ent.current_plan(_pro_bearer())
    assert get_mirror_session() is not None

def test_invalid_bearer_not_cached(auth_env):
    note_authenticated_mirror_session('Bearer not-a-jwt')
    assert get_mirror_session() is None