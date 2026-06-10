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
    ip._BUILT_MANIFEST_MTIME = None
    import shared.built_frontend as bf

    bf.invalidate_built_index_cache()
    monkeypatch.setattr(ip, "bundle_root", lambda: tmp_path)
    return mod


def test_built_index_html_rewrites_js_only_in_dev(server_mod):
    from shared.built_frontend import built_index_html

    html = built_index_html()
    assert html is not None
    assert 'href="tailwind.css"' in html
    assert 'href="app.css"' in html
    assert 'src="dist/js/app-CCCC.js"' in html
    assert 'href="dist/tailwind.AAAA.css"' not in html
    assert 'href="dist/app.BBBB.css"' not in html


def test_built_index_html_rewrites_css_when_frozen(server_mod, tmp_path, monkeypatch):
    from shared.built_frontend import built_index_html
    import shared.built_frontend as bf
    import shared.install_paths as ip

    monkeypatch.setattr(ip, "is_frozen", lambda: True)
    monkeypatch.setattr(ip, "bundle_root", lambda: tmp_path)
    monkeypatch.setattr(bf, "is_frozen", lambda: True)
    monkeypatch.setattr(bf, "bundle_root", lambda: tmp_path)
    bf.invalidate_built_index_cache()
    ip._BUILT_MANIFEST_CACHE = None
    ip._BUILT_MANIFEST_MTIME = None

    html = built_index_html()
    assert html is not None
    assert 'href="dist/tailwind.AAAA.css"' in html
    assert 'href="dist/app.BBBB.css"' in html
    assert 'src="dist/js/app-CCCC.js"' in html
    assert 'href="tailwind.css"' not in html


def test_built_index_invalidates_when_manifest_changes(server_mod, tmp_path):
    from shared.built_frontend import built_index_html

    html1 = built_index_html()
    assert 'src="dist/js/app-CCCC.js"' in html1
    dist = tmp_path / "dist"
    (dist / "manifest.json").write_text(
        '{"tailwind.css":"tailwind.AAAA.css","app.css":"app.BBBB.css","js/app.js":"js/app-DDDD.js","js/chunks":[]}',
        encoding="utf-8",
    )
    import shared.install_paths as ip

    ip._BUILT_MANIFEST_CACHE = None
    ip._BUILT_MANIFEST_MTIME = None
    import shared.built_frontend as bf

    bf.invalidate_built_index_cache()
    html2 = built_index_html()
    assert 'src="dist/js/app-DDDD.js"' in html2


def test_immutable_built_asset_detection(server_mod):
    assert server_mod._is_immutable_built_asset("/dist/app.BBBB.css")
    assert server_mod._is_immutable_built_asset("/dist/js/app-CCCC.js")
    assert not server_mod._is_immutable_built_asset("/app.css")
    assert not server_mod._is_immutable_built_asset("/js/app.js")
