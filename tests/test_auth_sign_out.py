from __future__ import annotations
import pytest
from shared import entitlement as ent
from shared.mirror_session import clear_mirror_session_for_tests, get_mirror_session, note_authenticated_mirror_session
from tests.test_server_mirror import _post_json, _pro_bearer
pytest_plugins = ['tests.test_server_supabase_auth']

@pytest.fixture(autouse=True)
def _reset_caches():
    clear_mirror_session_for_tests()
    ent._LAST_AUTH_PLAN = None
    yield
    clear_mirror_session_for_tests()
    ent._LAST_AUTH_PLAN = None

def test_auth_sign_out_clears_mirror_session(auth_server):
    base, secret, _tmp = auth_server
    note_authenticated_mirror_session(_pro_bearer(secret))
    ent.note_authenticated_plan('pro')
    assert get_mirror_session() is not None
    assert ent.is_pro_background() is True
    status, data = _post_json(base, '/api/auth/sign-out', {})
    assert status == 200
    assert data.get('ok') is True
    assert get_mirror_session() is None
    assert ent.is_pro_background() is False