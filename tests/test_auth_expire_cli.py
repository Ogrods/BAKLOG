import pytest

import auth.secrets as secrets
from auth.__main__ import main as auth_main
from auth.manager import mark_connected
from auth.registry import PROVIDERS
from auth.secrets import set_master_password_override
from shared import profile_paths


@pytest.fixture(autouse=True)
def isolated_default_profile(tmp_path, monkeypatch):
    prof_dir = tmp_path / "profiles"
    (prof_dir / "default").mkdir(parents=True)
    monkeypatch.setattr(profile_paths, "ROOT", tmp_path)
    monkeypatch.setattr(profile_paths, "PROFILES_DIR", prof_dir)
    monkeypatch.setattr(profile_paths, "INDEX_FILE", prof_dir / "index.json")
    monkeypatch.delenv("BAKLOG_PROFILE", raising=False)
    set_master_password_override("test-passphrase-auth-expire")
    secrets._cache = None
    target = profile_paths.auth_dir(profile_id="default")
    saved = (secrets.AUTH_DIR, secrets.SECRETS_FILE, secrets.MASTER_KEY_FILE, secrets._cache)
    secrets.AUTH_DIR = target
    secrets.SECRETS_FILE = target / "secrets.bin"
    secrets.MASTER_KEY_FILE = target / ".master_key"
    yield
    set_master_password_override(None)
    secrets.AUTH_DIR, secrets.SECRETS_FILE, secrets.MASTER_KEY_FILE, secrets._cache = saved


def test_expire_unknown_provider_returns_1():
    assert auth_main(["expire", "not_a_provider"]) == 1


def test_expire_list_returns_0(capsys):
    assert auth_main(["expire", "--list"]) == 0
    out = capsys.readouterr().out
    assert "gog" in out
    assert PROVIDERS["gog"].label in out


def test_expire_marks_connected_provider_expired():
    mark_connected("gog", {"GOG_AL": "fake-cookie"})
    assert auth_main(["expire", "gog"]) == 0
    blob = secrets.get_provider_blob("gog")
    assert blob.get("status") == "expired"
    assert blob.get("expired_at")
