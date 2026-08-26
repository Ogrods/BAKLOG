"""Unit tests for scripts/frozen_bundle_smoke.py (static checks only)."""

from __future__ import annotations

from pathlib import Path

import scripts.frozen_bundle_smoke as smoke
from shared.update_platform import server_binary_name, tray_binary_name


def _stub_bundle(tmp_path: Path, *, with_env: bool = True, with_pyproject: bool = True) -> Path:
    bundle = tmp_path / "BAKLOG"
    bundle.mkdir()
    (bundle / server_binary_name()).write_text("", encoding="utf-8")
    if with_pyproject:
        (bundle / "pyproject.toml").write_text(
            '[project]\nversion = "0.8.20"\n', encoding="utf-8"
        )
    tray = tray_binary_name()
    if tray:
        (bundle / tray).write_text("", encoding="utf-8")
    internal = bundle / "_internal" / "curated"
    internal.mkdir(parents=True)
    (internal / "free_claims.fallback.json").write_text("{}", encoding="utf-8")
    manifest_dir = bundle / "_internal" / "fetchers"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "manifest.json").write_text(
        '{"fetchers":[{"key":"steam"},{"key":"gog"}]}',
        encoding="utf-8",
    )
    if with_env:
        (bundle / ".env").write_text(
            "BAKLOG_SUPABASE_URL=https://demo.supabase.co\n"
            "BAKLOG_SUPABASE_ANON_KEY=anon-key\n",
            encoding="utf-8",
        )
    return bundle


def test_env_has_auth_keys_detects_missing(tmp_path: Path) -> None:
    bundle = _stub_bundle(tmp_path, with_env=False)
    ok, missing = smoke._env_has_auth_keys(bundle / ".env")
    assert not ok
    assert "BAKLOG_SUPABASE_URL" in missing
    assert "BAKLOG_SUPABASE_ANON_KEY" in missing


def test_manifest_fetcher_count(tmp_path: Path) -> None:
    bundle = _stub_bundle(tmp_path)
    assert smoke._manifest_fetcher_count(bundle) == 2


def test_run_smoke_fails_without_env(tmp_path: Path, monkeypatch) -> None:
    bundle = _stub_bundle(tmp_path, with_env=False)
    monkeypatch.setattr(smoke, "_read_expected_version", lambda: "0.8.20")
    report = smoke.run_smoke(bundle, expected_version="0.8.20")
    assert not report["ok"]
    assert "bundled .env" in (report.get("error") or "")


def test_run_smoke_does_not_nest_migration_smoke(tmp_path: Path, monkeypatch) -> None:
    """Migration runs as its own workflow step, on its own port."""
    bundle = _stub_bundle(tmp_path, with_env=False)
    monkeypatch.setattr(smoke, "_read_expected_version", lambda: "0.8.20")
    report = smoke.run_smoke(bundle, expected_version="0.8.20")
    assert "migration" not in report["checks"]
    assert report["port"] == smoke.BUNDLE_SMOKE_PORT


def test_run_smoke_requires_pyproject_at_bundle_root(tmp_path: Path, monkeypatch) -> None:
    """Frozen version detection reads bundle_root()/pyproject.toml, not _internal/."""
    bundle = _stub_bundle(tmp_path, with_pyproject=False)
    monkeypatch.setattr(smoke, "_read_expected_version", lambda: "0.8.20")
    report = smoke.run_smoke(bundle, expected_version="0.8.20")
    assert not report["ok"]
    assert report["checks"]["static"]["bundle_pyproject"] is False
    assert "pyproject.toml missing at bundle root" in (report.get("error") or "")


def test_unix_build_scripts_stage_pyproject_at_bundle_root() -> None:
    root = Path(__file__).resolve().parents[1]
    for script in ("build_linux.sh", "build_macos.sh"):
        text = (root / "packaging" / script).read_text(encoding="utf-8")
        assert '"${ROOT}/pyproject.toml" "${OUT_DIR}/pyproject.toml"' in text, script


def test_smoke_ports_are_distinct() -> None:
    from scripts.frozen_smoke_server import (
        BUNDLE_SMOKE_PORT,
        CONNECT_SMOKE_PORT,
        MIGRATION_SMOKE_PORT,
    )

    ports = {BUNDLE_SMOKE_PORT, MIGRATION_SMOKE_PORT, CONNECT_SMOKE_PORT}
    assert len(ports) == 3
    assert BUNDLE_SMOKE_PORT == 8765
