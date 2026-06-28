"""Regenerated js/fetcher-registry.js must match the committed file (no drift)."""

from __future__ import annotations

from pathlib import Path

from fetchers.registry import export_js_registry

ROOT = Path(__file__).resolve().parents[1]
COMMITTED = ROOT / "js" / "fetcher-registry.js"


def test_export_js_registry_matches_committed_file(tmp_path: Path) -> None:
    out = tmp_path / "fetcher-registry.js"
    export_js_registry(out)
    assert out.read_text(encoding="utf-8") == COMMITTED.read_text(encoding="utf-8")
