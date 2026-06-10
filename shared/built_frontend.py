"""Built-frontend index rewriting and immutable asset detection."""

from __future__ import annotations

import re
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler

from shared.install_paths import (
    built_immutable_assets,
    built_manifest_path,
    bundle_root,
    is_frozen,
    load_built_manifest,
    serve_built_frontend,
)

_BUILT_INDEX_HTML_CACHE: str | None = None
_BUILT_INDEX_MANIFEST_MTIME: float | None = None


def _built_index_manifest_mtime() -> float | None:
    try:
        return built_manifest_path().stat().st_mtime
    except OSError:
        return None


def built_index_html() -> str | None:
    """index.html with hashed dist/ asset URLs when serving built frontend."""
    global _BUILT_INDEX_HTML_CACHE, _BUILT_INDEX_MANIFEST_MTIME
    if not serve_built_frontend():
        return None
    mtime = _built_index_manifest_mtime()
    if mtime is None:
        return None
    if _BUILT_INDEX_HTML_CACHE is not None and _BUILT_INDEX_MANIFEST_MTIME == mtime:
        return _BUILT_INDEX_HTML_CACHE
    manifest = load_built_manifest()
    entry = manifest.get("js/app.js")
    tailwind = manifest.get("tailwind.css")
    app_css = manifest.get("app.css")
    if not entry:
        return None
    # Frozen builds ship hashed CSS with immutable cache. Dev built mode keeps
    # source CSS URLs so app.css/tailwind.css edits show on reload without
    # npm run build:css and without long-lived browser cache on dist/*.css.
    if is_frozen() and (not tailwind or not app_css):
        return None
    html = (bundle_root() / "index.html").read_text(encoding="utf-8")
    if is_frozen():
        html = html.replace('href="tailwind.css"', f'href="dist/{tailwind}"', 1)
        html = html.replace('href="app.css"', f'href="dist/{app_css}"', 1)
    html = html.replace('src="js/app.js"', f'src="dist/{entry}"', 1)
    _BUILT_INDEX_MANIFEST_MTIME = mtime
    _BUILT_INDEX_HTML_CACHE = html
    return html


def is_immutable_built_asset(path_only: str) -> bool:
    clean = path_only.lstrip("/").replace("\\", "/")
    if not clean.startswith("dist/"):
        return False
    rel = clean[len("dist/") :]
    immutable = built_immutable_assets()
    if rel in immutable:
        return True
    if rel.startswith("js/chunks/") and rel in immutable:
        return True
    return bool(re.search(r"\.[a-f0-9]{8}\.", rel))


def maybe_serve_built_index(
    handler: SimpleHTTPRequestHandler, path_only: str
) -> bool:
    if path_only not in ("/", "/index.html"):
        return False
    html = built_index_html()
    if html is None:
        return False
    body = html.encode("utf-8")
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)
    return True


def invalidate_built_index_cache() -> None:
    """Clear cached rewritten index (tests)."""
    global _BUILT_INDEX_HTML_CACHE, _BUILT_INDEX_MANIFEST_MTIME
    _BUILT_INDEX_HTML_CACHE = None
    _BUILT_INDEX_MANIFEST_MTIME = None
