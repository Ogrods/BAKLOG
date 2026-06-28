"""POST /api/catalogs/import — restore games_*.json / itad_prices.json from a backup."""

from __future__ import annotations

import json
import re
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler
from typing import Any

CATALOG_IMPORT_MAX_BYTES = 128 * 1024 * 1024
_ALLOWED_CATALOG_RE = re.compile(r"^(games_[a-z0-9_]+\.json|itad_prices\.json)$")


def _srv():
    import server

    return server


def is_allowed_catalog_filename(name: str) -> bool:
    return bool(_ALLOWED_CATALOG_RE.match(str(name or "")))


def validate_catalog_doc(filename: str, doc: Any) -> None:
    if not isinstance(doc, dict):
        raise ValueError(f"{filename}: must be a JSON object")
    if filename == "itad_prices.json":
        return
    games = doc.get("games")
    if games is not None and not isinstance(games, list):
        raise ValueError(f"{filename}: games must be a list")


def import_catalog_payload(payload: dict[str, Any]) -> dict[str, Any]:
    from shared.profile_paths import catalog_path, get_active_profile_id
    from shared.safe_write import safe_write_text

    catalogs = payload.get("catalogs")
    if not isinstance(catalogs, dict):
        raise ValueError("payload.catalogs must be an object")
    if not catalogs:
        raise ValueError("payload.catalogs is empty")

    claimed = payload.get("profile")
    profile_id = get_active_profile_id()
    if claimed is not None and str(claimed) != profile_id:
        raise ValueError(
            f"profile mismatch (active={profile_id!r}, claimed={str(claimed)!r})"
        )

    imported: list[str] = []
    for name, doc in catalogs.items():
        if not is_allowed_catalog_filename(name):
            raise ValueError(f"disallowed catalog filename: {name}")
        validate_catalog_doc(name, doc)
        path = catalog_path(name, profile_id=profile_id)
        text = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
        safe_write_text(path, text)
        imported.append(name)

    return {"ok": True, "imported": imported, "count": len(imported)}


def handle_catalogs_import_post(handler: SimpleHTTPRequestHandler) -> None:
    s = _srv()
    payload, err = s._read_json_body(handler, max_bytes=CATALOG_IMPORT_MAX_BYTES)
    if err:
        s._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": err})
        return
    if payload is None:
        s._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "empty body"})
        return
    try:
        result = import_catalog_payload(payload)
    except ValueError as exc:
        msg = str(exc)
        if msg.startswith("profile mismatch"):
            s._send_json(handler, HTTPStatus.CONFLICT, {"error": msg})
            return
        s._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": msg})
        return
    except OSError as exc:
        s._api_error(handler, HTTPStatus.INTERNAL_SERVER_ERROR, "catalog_import_failed", exc)
        return
    s._send_json(handler, HTTPStatus.OK, result)
