import json

import pytest

from scripts import release_notes


def test_repo_version_stamps_agree():
    stamps = release_notes.read_version_stamps()
    assert len(set(stamps.values())) == 1, stamps


def _fake_repo(tmp_path, mirror_version="1.2.3"):
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.2.3"\n', encoding="utf-8")
    (tmp_path / "package.json").write_text(json.dumps({"version": "1.2.3"}), encoding="utf-8")
    (tmp_path / "web" / "mirror").mkdir(parents=True)
    meta = '<meta name="baklog-version" content="{}" />'
    (tmp_path / "index.html").write_text(meta.format("1.2.3"), encoding="utf-8")
    (tmp_path / "web" / "mirror" / "index.html").write_text(meta.format(mirror_version), encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n## [1.2.3] - 2026-10-01\n\n### Added\n\n- Thing\n\n"
        "## [1.2.2] - 2026-09-01\n\n- Older\n",
        encoding="utf-8",
    )
    return tmp_path


def test_mirror_stamp_drift_detected(tmp_path):
    stamps = release_notes.read_version_stamps(_fake_repo(tmp_path, mirror_version="1.2.2"))
    assert stamps["web/mirror/index.html"] == "1.2.2"
    assert len(set(stamps.values())) == 2


def test_changelog_section_extracts_only_that_version(tmp_path):
    root = _fake_repo(tmp_path)
    assert release_notes.changelog_section("1.2.3", root) == "### Added\n\n- Thing"
    assert release_notes.changelog_section("1.2.2", root) == "- Older"
    assert release_notes.changelog_section("9.9.9", root) == ""


def test_pyproject_version_read_from_project_table_only(tmp_path):
    root = _fake_repo(tmp_path)
    (root / "pyproject.toml").write_text(
        '[tool.other]\nversion = "0.0.1"\n\n[project]\nname = "baklog"\nversion = "1.2.3"\n',
        encoding="utf-8",
    )
    assert release_notes.read_version_stamps(root)["pyproject.toml"] == "1.2.3"


def test_pyproject_without_project_version_fails(tmp_path):
    root = _fake_repo(tmp_path)
    (root / "pyproject.toml").write_text('[tool.other]\nversion = "0.0.1"\n', encoding="utf-8")
    with pytest.raises(ValueError, match=r"\[project\] version"):
        release_notes.read_version_stamps(root)


def test_notes_refuses_heading_only_section(tmp_path, capsys):
    root = _fake_repo(tmp_path)
    (root / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [1.2.3] - 2026-10-01\n\n### Added\n\n### Fixed\n\n## [1.2.2]\n\n- Older\n",
        encoding="utf-8",
    )
    assert release_notes._cmd_notes("v1.2.3", None, root) == 1
    assert "notes under it" in capsys.readouterr().err


def test_notes_writes_section_with_bullets(tmp_path):
    root = _fake_repo(tmp_path)
    out = tmp_path / "notes.md"
    assert release_notes._cmd_notes("v1.2.3", str(out), root) == 0
    assert out.read_text(encoding="utf-8") == "### Added\n\n- Thing\n"
