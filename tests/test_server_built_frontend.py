"""Tests for built-frontend index rewriting and cache headers."""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture()
def server_mod(monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "manifest.json").write_text(
        '{"tailwind.css":"tailwind.AAAA.css","app.css":"app.BBBB.css","js/app.js":"js/app-CCCC.js","js/chunks":[]}',
        encoding="utf-8",
    )
    index = tmp_path / "index.html"
    index.write_text(
        '<link rel="stylesheet" href="tailwind.css" />\n'
        '<link rel="stylesheet" href="app.css" />\n'
        '<script type="module" src="js/app.js"></script>\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("BAKLOG_SERVE_BUILT", "1")
    import server as mod

    importlib.reload(mod)
    monkeypatch.setattr(mod, "bundle_root", lambda: tmp_path)
    import shared.install_paths as ip

    ip._BUILT_MANIFEST_CACHE = None
    mod._BUILT_INDEX_HTML_CACHE = None
    monkeypatch.setattr(ip, "bundle_root", lambda: tmp_path)
    return mod


def test_built_index_html_rewrites_asset_urls(server_mod):
    html = server_mod._built_index_html()
    assert html is not None
    assert 'href="dist/tailwind.AAAA.css"' in html
    assert 'href="dist/app.BBBB.css"' in html
    assert 'src="dist/js/app-CCCC.js"' in html
    assert 'href="tailwind.css"' not in html


def test_immutable_built_asset_detection(server_mod):
    assert server_mod._is_immutable_built_asset("/dist/app.BBBB.css")
    assert server_mod._is_immutable_built_asset("/dist/js/app-CCCC.js")
    assert not server_mod._is_immutable_built_asset("/app.css")
    assert not server_mod._is_immutable_built_asset("/js/app.js")
