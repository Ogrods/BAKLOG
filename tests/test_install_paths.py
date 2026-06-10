"""Tests for shared.install_paths."""

from __future__ import annotations

import os
import time
from pathlib import Path

from shared import install_paths


def test_dev_roots_align(monkeypatch):
    monkeypatch.delenv("BAKLOG_DATA_DIR", raising=False)
    monkeypatch.setattr(install_paths, "is_frozen", lambda: False)
    root = Path(__file__).resolve().parents[1]
    assert install_paths.bundle_root() == root
    assert install_paths.data_root() == root
    assert install_paths.static_root() == root


def test_data_dir_override(monkeypatch, tmp_path):
    monkeypatch.setenv("BAKLOG_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(install_paths, "is_frozen", lambda: False)
    assert install_paths.data_root() == tmp_path.resolve()


def test_serve_built_false_without_manifest(monkeypatch, tmp_path):
    monkeypatch.delenv("BAKLOG_SERVE_BUILT", raising=False)
    monkeypatch.setattr(install_paths, "is_frozen", lambda: False)
    monkeypatch.setattr(install_paths, "bundle_root", lambda: tmp_path)
    install_paths._BUILT_MANIFEST_CACHE = None
    install_paths._BUILT_MANIFEST_MTIME_NS = None
    assert install_paths.serve_built_frontend() is False
    assert install_paths.load_built_manifest() == {}


def test_manifest_cache_invalidates_on_mtime_change(monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    manifest = dist / "manifest.json"
    manifest.write_text('{"js/app.js":"js/app-OLD.js"}', encoding="utf-8")
    monkeypatch.setenv("BAKLOG_SERVE_BUILT", "1")
    monkeypatch.setattr(install_paths, "is_frozen", lambda: False)
    monkeypatch.setattr(install_paths, "bundle_root", lambda: tmp_path)
    install_paths._BUILT_MANIFEST_CACHE = None
    install_paths._BUILT_MANIFEST_MTIME_NS = None
    assert install_paths.load_built_manifest()["js/app.js"] == "js/app-OLD.js"
    manifest.write_text('{"js/app.js":"js/app-NEW.js"}', encoding="utf-8")
    # Windows runners can expose coarse st_mtime; bump explicitly so invalidation is observable.
    os.utime(manifest, (time.time() + 1, time.time() + 1))
    assert install_paths.load_built_manifest()["js/app.js"] == "js/app-NEW.js"


def test_serve_built_true_with_flag_and_manifest(monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "manifest.json").write_text(
        '{"app.css":"app.abc.css","js/app.js":"js/app-XYZ.js","js/chunks":[]}',
        encoding="utf-8",
    )
    monkeypatch.setenv("BAKLOG_SERVE_BUILT", "1")
    monkeypatch.setattr(install_paths, "is_frozen", lambda: False)
    monkeypatch.setattr(install_paths, "bundle_root", lambda: tmp_path)
    install_paths._BUILT_MANIFEST_CACHE = None
    install_paths._BUILT_MANIFEST_MTIME_NS = None
    assert install_paths.serve_built_frontend() is True
    manifest = install_paths.load_built_manifest()
    assert manifest["app.css"] == "app.abc.css"
    assets = install_paths.built_immutable_assets()
    assert "app.abc.css" in assets
    assert "js/app-XYZ.js" in assets
