import shutil

import pytest

import auth.secrets as secrets_mod
from auth.bundle import (
    MAGIC,
    BadMagic,
    BadPassphrase,
    BundleTooLarge,
    UnsupportedVersion,
    export_bundle,
    import_bundle,
    parse_bundle_header,
)
from auth.manager import get_credentials, mark_connected
from auth.secrets import load_doc, set_master_password_override


@pytest.fixture(autouse=True)
def _isolated_auth(tmp_path, monkeypatch):
    auth_dir = tmp_path / "auth"
    profiles_root = auth_dir / "profiles"
    profiles_root.mkdir(parents=True, exist_ok=True)
    secrets_file = auth_dir / "secrets.bin"
    monkeypatch.setattr("auth.secrets.AUTH_DIR", auth_dir)
    monkeypatch.setattr("auth.secrets.SECRETS_FILE", secrets_file)
    monkeypatch.setattr("auth.secrets.MASTER_KEY_FILE", auth_dir / ".master_key")
    secrets_mod._cache = None
    set_master_password_override("test-passphrase-for-unit-tests")
    yield auth_dir
    set_master_password_override(None)
    secrets_mod._cache = None
    if secrets_file.exists():
        secrets_file.unlink()


PASS = "unit-test-passphrase-123"


def test_roundtrip_credentials_only():
    mark_connected("steam", {"STEAM_API_KEY": "abc123", "STEAM_ID": "76561198000000000"})
    mark_connected("itch", {"ITCH_API_KEY": "itch-key-value-here"})
    blob = export_bundle(PASS, include_profiles=False)
    assert parse_bundle_header(blob)["version"] == 1
    secrets_mod.SECRETS_FILE.unlink(missing_ok=True)
    secrets_mod._cache = None
    summary = import_bundle(blob, PASS)
    assert summary.providers_imported == ["itch", "steam"]
    assert get_credentials("steam")["STEAM_API_KEY"] == "abc123"
    assert get_credentials("itch")["ITCH_API_KEY"] == "itch-key-value-here"


def test_roundtrip_with_profiles(_isolated_auth):
    mark_connected("gog", {"GOG_AL": "cookie-value"})
    gog_dir = _isolated_auth / "profiles" / "gog" / "Default"
    gog_dir.mkdir(parents=True)
    cookie_file = gog_dir / "Cookies"
    cookie_file.write_bytes(b"sqlite-cookie-bytes")
    meta = gog_dir / "Preferences"
    meta.write_text('{"lang":"en"}', encoding="utf-8")
    blob = export_bundle(PASS, include_profiles=True)
    secrets_mod.SECRETS_FILE.unlink(missing_ok=True)
    shutil.rmtree(_isolated_auth / "profiles", ignore_errors=True)
    secrets_mod._cache = None
    summary = import_bundle(blob, PASS)
    assert "gog" in summary.profiles_imported
    assert (_isolated_auth / "profiles" / "gog" / "Default" / "Cookies").read_bytes() == b"sqlite-cookie-bytes"
    assert get_credentials("gog")["GOG_AL"] == "cookie-value"


def test_bad_passphrase_rejected():
    mark_connected("steam", {"STEAM_API_KEY": "x", "STEAM_ID": "76561198000000000"})
    blob = export_bundle(PASS)
    with pytest.raises(BadPassphrase):
        import_bundle(blob, "wrong-passphrase-here")
    assert get_credentials("steam")["STEAM_API_KEY"] == "x"


def test_bad_magic_rejected():
    mark_connected("steam", {"STEAM_API_KEY": "x", "STEAM_ID": "76561198000000000"})
    blob = bytearray(export_bundle(PASS))
    blob[0] ^= 255
    with pytest.raises(BadMagic):
        import_bundle(bytes(blob), PASS)


def test_unsupported_version_rejected():
    blob = bytearray(export_bundle(PASS))
    blob[len(MAGIC)] = 99
    with pytest.raises(UnsupportedVersion):
        import_bundle(bytes(blob), PASS)


def test_passphrase_minimum_length():
    with pytest.raises(ValueError, match="at least 8"):
        export_bundle("short")


def test_too_large_rejected():
    huge = b"x" * (100 * 1024 * 1024 + 1)
    with pytest.raises(BundleTooLarge):
        import_bundle(huge, PASS)


def test_pre_import_snapshot_taken(_isolated_auth):
    mark_connected("psn", {"PSN_NPSSO": "npsso"})
    old_profiles = _isolated_auth / "profiles" / "psn"
    old_profiles.mkdir(parents=True)
    (old_profiles / "Default" / "Cookies").parent.mkdir(parents=True, exist_ok=True)
    (old_profiles / "Default" / "Cookies").write_bytes(b"old")
    blob = export_bundle(PASS)
    import_bundle(blob, PASS)
    snapshots = list(_isolated_auth.glob("profiles_pre_import_*"))
    assert len(snapshots) == 1
    assert (snapshots[0] / "psn" / "Default" / "Cookies").read_bytes() == b"old"


def test_dry_run_changes_nothing():
    mark_connected("nintendo", {"NINTENDO_COOKIE": "c=1"})
    blob = export_bundle(PASS)
    before = load_doc()
    summary = import_bundle(blob, PASS, dry_run=True)
    assert summary.dry_run is True
    assert summary.providers_imported == ["nintendo"]
    assert load_doc() == before
