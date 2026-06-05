"""Tests for shared.install_paths."""

from __future__ import annotations

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
