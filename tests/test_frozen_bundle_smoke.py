"""Unit tests for scripts/frozen_bundle_smoke.py (static checks only)."""

from __future__ import annotations

from pathlib import Path

import scripts.frozen_bundle_smoke as smoke


def _stub_bundle(tmp_path: Path, *, with_env: bool = True) -> Path:
    bundle = tmp_path / "BAKLOG"
    bundle.mkdir()
    (bundle / "BAKLOG.exe").write_text("", encoding="utf-8")
    (bundle / "BAKLOG Tray.exe").write_text("", encoding="utf-8")
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
