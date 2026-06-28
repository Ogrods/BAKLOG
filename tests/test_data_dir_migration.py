from shared.data_dir_migration import (
    legacy_has_user_artifacts,
    migrate_legacy_colocated_data,
    migration_marker_path,
    target_has_meaningful_data,
)


def test_legacy_has_user_artifacts_detects_profiles(tmp_path):
    legacy = tmp_path / "install"
    legacy.mkdir()
    assert legacy_has_user_artifacts(legacy) is False
    (legacy / "profiles").mkdir()
    assert legacy_has_user_artifacts(legacy) is True


def test_target_has_meaningful_data_detects_index(tmp_path):
    target = tmp_path / "data"
    target.mkdir()
    assert target_has_meaningful_data(target) is False
    prof = target / "profiles"
    prof.mkdir()
    (prof / "index.json").write_text("{}", encoding="utf-8")
    assert target_has_meaningful_data(target) is True


def test_target_has_meaningful_data_ignores_secrets_bin_only(tmp_path):
    target = tmp_path / "data"
    auth = target / "cache" / "auth"
    auth.mkdir(parents=True)
    (auth / "secrets.bin").write_bytes(b"stub")
    assert target_has_meaningful_data(target) is False


def test_migrate_moves_legacy_profiles_and_games(tmp_path):
    legacy = tmp_path / "install"
    target = tmp_path / "userdata"
    legacy.mkdir()
    (legacy / "profiles").mkdir()
    (legacy / "profiles" / "index.json").write_text('{"active":"default"}', encoding="utf-8")
    (legacy / "games_steam.json").write_text('{"games":[]}', encoding="utf-8")
    notes = migrate_legacy_colocated_data(legacy, target)
    assert notes
    assert (target / "profiles" / "index.json").is_file()
    assert (target / "games_steam.json").is_file()
    assert not (legacy / "profiles").exists()
    assert migration_marker_path(target).is_file()
    assert migrate_legacy_colocated_data(legacy, target) == []


def test_migrate_resumes_when_target_partially_populated(tmp_path):
    legacy = tmp_path / "install"
    target = tmp_path / "userdata"
    legacy.mkdir()
    target.mkdir()
    (legacy / "games_steam.json").write_text('{"games":[]}', encoding="utf-8")
    (target / "games_gog.json").write_text("{}", encoding="utf-8")
    prof = target / "profiles"
    prof.mkdir()
    (prof / "index.json").write_text('{"active":"default"}', encoding="utf-8")
    notes = migrate_legacy_colocated_data(legacy, target)
    assert notes
    assert (target / "games_steam.json").is_file()
    assert (target / "games_gog.json").is_file()
    assert not (legacy / "games_steam.json").exists()
    assert migration_marker_path(target).is_file()


def test_migrate_resumes_profiles_in_target_games_in_legacy(tmp_path):
    legacy = tmp_path / "install"
    target = tmp_path / "userdata"
    legacy.mkdir()
    target.mkdir()
    (legacy / "games_steam.json").write_text('{"games":[]}', encoding="utf-8")
    (target / "profiles").mkdir()
    (target / "profiles" / "index.json").write_text('{"active":"default"}', encoding="utf-8")
    migrate_legacy_colocated_data(legacy, target)
    assert (target / "games_steam.json").is_file()
    assert not legacy_has_user_artifacts(legacy)
    assert migration_marker_path(target).is_file()


def test_migrate_skips_when_legacy_empty(tmp_path):
    legacy = tmp_path / "install"
    target = tmp_path / "userdata"
    legacy.mkdir()
    assert migrate_legacy_colocated_data(legacy, target) == []
    assert not migration_marker_path(target).exists()
