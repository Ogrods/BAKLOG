"""Admin-only /api/internal/* route handlers (keeps server.py lean)."""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler
from typing import Any


def _is_safe_http_url(url: str) -> bool:
    u = str(url or "").strip()
    return u.startswith("http://") or u.startswith("https://")


def _srv():
    import server

    return server


def validate_free_claims_payload(doc: dict[str, Any]) -> str | None:
    s = _srv()
    items = doc.get("items")
    if not isinstance(items, list):
        return "items must be a list"
    too_large = s._admin_list_too_large(
        items, cap=s.MAX_ADMIN_CLAIM_ITEMS, label="items",
    )
    if too_large:
        return too_large
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            return f"items[{i}] must be an object"
        for field in ("id", "store", "title", "claim_url"):
            if not str(item.get(field) or "").strip():
                return f"items[{i}] missing {field}"
        if not _is_safe_http_url(str(item.get("claim_url") or "")):
            return f"items[{i}] claim_url must start with http:// or https://"
        premium_only = item.get("premium_only")
        if premium_only is not None and not isinstance(premium_only, bool):
            return f"items[{i}] premium_only must be a boolean"
    return None


def validate_approved_payload(doc: dict[str, Any]) -> str | None:
    ids = doc.get("ids")
    if not isinstance(ids, list):
        return "ids must be a list"
    for i, item_id in enumerate(ids):
        if not str(item_id or "").strip():
            return f"ids[{i}] must be a non-empty string"
    overrides = doc.get("store_overrides")
    if overrides is not None:
        if not isinstance(overrides, dict):
            return "store_overrides must be an object"
        for key, val in overrides.items():
            if not str(val or "").strip():
                return f"store_overrides[{key}] must be a non-empty string"
    field_overrides = doc.get("field_overrides")
    if field_overrides is not None:
        if not isinstance(field_overrides, dict):
            return "field_overrides must be an object"
        allowed = {"title", "claim_url", "ends_at"}
        for key, val in field_overrides.items():
            if not isinstance(val, dict):
                return f"field_overrides[{key}] must be an object"
            for field, field_val in val.items():
                if field not in allowed:
                    return f"field_overrides[{key}] unknown key {field!r}"
                if field in ("title", "claim_url") and not str(field_val or "").strip():
                    return f"field_overrides[{key}][{field}] must be a non-empty string"
                if field == "claim_url" and not _is_safe_http_url(str(field_val or "")):
                    return f"field_overrides[{key}][claim_url] must start with http:// or https://"
                if field == "ends_at" and field_val is not None and not str(field_val).strip():
                    return f"field_overrides[{key}][ends_at] must be a non-empty string"
    dismissed = doc.get("dismissed")
    if dismissed is not None:
        if not isinstance(dismissed, list):
            return "dismissed must be a list"
        for i, item_id in enumerate(dismissed):
            if not str(item_id or "").strip():
                return f"dismissed[{i}] must be a non-empty string"
    blocked = doc.get("blocked")
    if blocked is not None:
        if not isinstance(blocked, list):
            return "blocked must be a list"
        for i, item_id in enumerate(blocked):
            if not str(item_id or "").strip():
                return f"blocked[{i}] must be a non-empty string"
    premium_only_ids = doc.get("premium_only_ids")
    if premium_only_ids is not None:
        if not isinstance(premium_only_ids, list):
            return "premium_only_ids must be a list"
        for i, item_id in enumerate(premium_only_ids):
            if not str(item_id or "").strip():
                return f"premium_only_ids[{i}] must be a non-empty string"
    return None


def handle_internal_jobs_get(handler: SimpleHTTPRequestHandler) -> None:
    s = _srv()
    jobs = [
        {
            "key": key,
            "label": spec["label"],
            "group": spec.get("group", "internal"),
            "description": spec.get("description", ""),
            "options": spec.get("options") or {},
        }
        for key, spec in s.INTERNAL_JOBS.items()
    ]
    s._send_json(handler, HTTPStatus.OK, {"jobs": jobs})


def handle_internal_submit(handler: SimpleHTTPRequestHandler, key: str) -> None:
    s = _srv()
    if key not in s.INTERNAL_JOBS:
        s._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"unknown internal job: {key}"})
        return
    payload, err = s._read_json_body(handler)
    if err == "empty body":
        payload = {}
    elif err:
        s._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": err})
        return
    assert payload is not None
    args_in = payload.get("args") or {}
    if not isinstance(args_in, dict):
        s._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "args must be an object"})
        return
    try:
        extra = s.validate_internal_args(s.INTERNAL_JOBS[key], args_in)
    except ValueError as exc:
        s._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        return
    try:
        run = s.MANAGER.submit_internal(key, extra)
    except ValueError as exc:
        s._send_json(handler, HTTPStatus.CONFLICT, {"error": str(exc)})
        return
    s._send_json(
        handler,
        HTTPStatus.ACCEPTED,
        {
            "run_id": run.id,
            "key": run.key,
            "label": run.label,
            "status": run.status,
        },
    )


def handle_internal_free_claims_enrich(handler: SimpleHTTPRequestHandler) -> None:
    s = _srv()
    payload, err = s._read_json_body(handler)
    if err:
        s._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": err})
        return
    assert payload is not None
    items = payload.get("items")
    if not isinstance(items, list):
        s._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "items must be a list"})
        return
    too_large = s._admin_list_too_large(
        items, cap=s.MAX_ADMIN_ENRICH_BATCH, label="enrich items",
    )
    if too_large:
        s._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": too_large})
        return
    from fetchers.build_free_claims import (
        _build_cover_lookup,
        _enrich_item,
        merge_enriched_items_into_auto_feed,
        merge_enriched_items_into_input_feed,
    )

    cover_lookup = _build_cover_lookup(
        [raw for raw in items if isinstance(raw, dict)]
    )
    last_call = [0.0]
    enriched: list[dict[str, Any]] = []
    for raw in items:
        if not isinstance(raw, dict):
            enriched.append({})
            continue
        enriched.append(
            _enrich_item(raw, last_call, cover_lookup, upgrade_covers=True)
        )

    root = s.data_root()
    auto_path = root / s.FREE_CLAIMS_AUTO_PATH
    input_path = root / s.FREE_CLAIMS_INPUT_PATH
    auto_doc = s._read_optional_json(auto_path) or {}
    input_doc = s._read_optional_json(input_path) or {}
    auto_ids = {
        str(it.get("id") or "").strip()
        for it in (auto_doc.get("items") or [])
        if isinstance(it, dict) and str(it.get("id") or "").strip()
    }
    manual_ids = {
        str(it.get("id") or "").strip()
        for it in (input_doc.get("items") or [])
        if isinstance(it, dict) and str(it.get("id") or "").strip()
    }
    to_persist_auto = [
        row for row in enriched
        if isinstance(row, dict) and str(row.get("id") or "").strip() in auto_ids
    ]
    to_persist_manual = [
        row for row in enriched
        if isinstance(row, dict) and str(row.get("id") or "").strip() in manual_ids
    ]
    persisted_auto = merge_enriched_items_into_auto_feed(auto_path, to_persist_auto)
    persisted_manual = merge_enriched_items_into_input_feed(input_path, to_persist_manual)

    s._send_json(
        handler,
        HTTPStatus.OK,
        {
            "items": enriched,
            "count": len(enriched),
            "persisted": persisted_auto + persisted_manual,
            "persisted_auto": persisted_auto,
            "persisted_manual": persisted_manual,
        },
    )


def handle_internal_free_claims_preview(handler: SimpleHTTPRequestHandler) -> None:
    s = _srv()
    payload, err = s._read_json_body(handler)
    if err:
        s._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": err})
        return
    assert payload is not None
    manual_items = payload.get("manual_items")
    auto_items = payload.get("auto_items")
    approved = payload.get("approved_ids")
    if manual_items is not None and not isinstance(manual_items, list):
        s._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "manual_items must be a list"})
        return
    if auto_items is not None and not isinstance(auto_items, list):
        s._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "auto_items must be a list"})
        return
    if approved is not None and not isinstance(approved, list):
        s._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "approved_ids must be a list"})
        return
    dismissed = payload.get("dismissed")
    if dismissed is not None and not isinstance(dismissed, list):
        s._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "dismissed must be a list"})
        return
    blocked = payload.get("blocked")
    if blocked is not None and not isinstance(blocked, list):
        s._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "blocked must be a list"})
        return
    premium_only = payload.get("premium_only_ids")
    if premium_only is not None and not isinstance(premium_only, list):
        s._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "premium_only_ids must be a list"})
        return

    root = s.data_root()
    if manual_items is None:
        manual_doc = s._read_optional_json(root / s.FREE_CLAIMS_INPUT_PATH) or {}
        manual_items = manual_doc.get("items") or []
    if auto_items is None:
        auto_doc = s._read_optional_json(root / s.FREE_CLAIMS_AUTO_PATH) or {}
        auto_items = auto_doc.get("items") or []
    if approved is None:
        approved_doc = s._read_optional_json(root / s.FREE_CLAIMS_APPROVED_PATH) or {}
        approved = approved_doc.get("ids") or []

    store_overrides = payload.get("store_overrides")
    if store_overrides is None:
        approved_doc = s._read_optional_json(root / s.FREE_CLAIMS_APPROVED_PATH) or {}
        store_overrides = approved_doc.get("store_overrides") or {}
    field_overrides = payload.get("field_overrides")
    if field_overrides is None:
        approved_doc = s._read_optional_json(root / s.FREE_CLAIMS_APPROVED_PATH) or {}
        field_overrides = approved_doc.get("field_overrides") or {}
    if dismissed is None:
        approved_doc = s._read_optional_json(root / s.FREE_CLAIMS_APPROVED_PATH) or {}
        dismissed = approved_doc.get("dismissed") or []
    if blocked is None:
        approved_doc = s._read_optional_json(root / s.FREE_CLAIMS_APPROVED_PATH) or {}
        blocked = approved_doc.get("blocked") or []
    premium_only_ids_payload = payload.get("premium_only_ids")
    if premium_only_ids_payload is None:
        approved_doc = s._read_optional_json(root / s.FREE_CLAIMS_APPROVED_PATH) or {}
        premium_only_ids_payload = approved_doc.get("premium_only_ids") or []

    if not isinstance(store_overrides, dict):
        s._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "store_overrides must be an object"})
        return
    if not isinstance(field_overrides, dict):
        s._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "field_overrides must be an object"})
        return

    manual_list = [it for it in (manual_items or []) if isinstance(it, dict)]
    auto_list = [it for it in (auto_items or []) if isinstance(it, dict)]
    for label, lst in (("manual_items", manual_list), ("auto_items", auto_list)):
        too_large = s._admin_list_too_large(lst, cap=s.MAX_ADMIN_CLAIM_ITEMS, label=label)
        if too_large:
            s._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": too_large})
            return

    from fetchers.build_free_claims import preview_publish_items, require_manual_approval_enabled

    approved_ids = {
        str(item_id).strip()
        for item_id in approved
        if str(item_id).strip()
    }
    clean_store: dict[str, str] = {}
    for key, val in store_overrides.items():
        k = str(key).strip()
        v = str(val or "").strip().lower()
        if k and v:
            clean_store[k] = v
    dismissed_ids = {
        str(item_id).strip()
        for item_id in (dismissed or [])
        if str(item_id).strip()
    }
    blocked_ids = {
        str(item_id).strip()
        for item_id in (blocked or [])
        if str(item_id).strip()
    }
    dismissed_ids |= blocked_ids
    premium_only_ids = {
        str(item_id).strip()
        for item_id in (premium_only_ids_payload or [])
        if str(item_id).strip()
    }

    built_doc = s._read_optional_json(root / s.FREE_CLAIMS_BUILT_PATH) or {}
    live_items = [
        it for it in (built_doc.get("items") or []) if isinstance(it, dict)
    ]

    items = preview_publish_items(
        manual_items=manual_list,
        auto_items_all=auto_list,
        approved_ids=approved_ids,
        store_overrides=clean_store,
        field_overrides={
            str(k).strip(): v
            for k, v in field_overrides.items()
            if str(k).strip() and isinstance(v, dict)
        },
        dismissed_ids=dismissed_ids,
        live_items=live_items,
        premium_only_ids=premium_only_ids,
        require_manual_approval=require_manual_approval_enabled(),
    )
    from fetchers.build_free_claims import GAMERPOWER_ATTRIBUTION

    attribution = (
        [GAMERPOWER_ATTRIBUTION]
        if any(item.get("source") == "gamerpower" for item in items)
        else []
    )
    s._send_json(
        handler,
        HTTPStatus.OK,
        {"items": items, "count": len(items), "attribution": attribution},
    )


def handle_internal_free_claims_get(handler: SimpleHTTPRequestHandler) -> None:
    s = _srv()
    root = s.data_root()
    approved_doc = s._read_optional_json(root / s.FREE_CLAIMS_APPROVED_PATH) or {}
    approved_ids = approved_doc.get("ids") or []
    if not isinstance(approved_ids, list):
        approved_ids = []
    store_overrides = approved_doc.get("store_overrides")
    if not isinstance(store_overrides, dict):
        store_overrides = {}
    field_overrides = approved_doc.get("field_overrides")
    if not isinstance(field_overrides, dict):
        field_overrides = {}
    dismissed = approved_doc.get("dismissed")
    if not isinstance(dismissed, list):
        dismissed = []
    blocked = approved_doc.get("blocked")
    if not isinstance(blocked, list):
        blocked = []
    premium_only_ids = approved_doc.get("premium_only_ids")
    if not isinstance(premium_only_ids, list):
        premium_only_ids = []
    s._send_json(
        handler,
        HTTPStatus.OK,
        {
            "input": s._read_optional_json(root / s.FREE_CLAIMS_INPUT_PATH) or {"items": []},
            "auto": s._read_optional_json(root / s.FREE_CLAIMS_AUTO_PATH),
            "approved": approved_ids,
            "store_overrides": store_overrides,
            "field_overrides": field_overrides,
            "dismissed": dismissed,
            "blocked": blocked,
            "premium_only_ids": premium_only_ids,
            "built": s._read_optional_json(root / s.FREE_CLAIMS_BUILT_PATH),
        },
    )


def handle_internal_free_claims_put(handler: SimpleHTTPRequestHandler) -> None:
    s = _srv()
    from shared.safe_write import safe_write_text

    payload, err = s._read_json_body(handler)
    if err:
        s._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": err})
        return
    assert payload is not None
    validation_err = validate_free_claims_payload(payload)
    if validation_err:
        s._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": validation_err})
        return
    out_path = s._resolve_contained_data_path(s.FREE_CLAIMS_INPUT_PATH)
    if out_path is None:
        s._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "invalid free-claims input path"})
        return
    out_path.parent.mkdir(parents=True, exist_ok=True)
    safe_write_text(
        out_path,
        json.dumps(payload, indent=2, ensure_ascii=False),
    )
    s._send_json(handler, HTTPStatus.OK, {"ok": True, "items": len(payload.get("items") or [])})


def handle_internal_free_claims_approved_put(handler: SimpleHTTPRequestHandler) -> None:
    s = _srv()
    from shared.safe_write import safe_write_text

    payload, err = s._read_json_body(handler)
    if err:
        s._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": err})
        return
    assert payload is not None
    validation_err = validate_approved_payload(payload)
    if validation_err:
        s._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": validation_err})
        return
    from fetchers.build_free_claims import parse_approved_put_payload, prepare_approved_document

    parsed = parse_approved_put_payload(payload)
    root = s.data_root()
    auto_doc = s._read_optional_json(root / s.FREE_CLAIMS_AUTO_PATH) or {}
    auto_items = [it for it in (auto_doc.get("items") or []) if isinstance(it, dict)]
    built_doc = s._read_optional_json(root / s.FREE_CLAIMS_BUILT_PATH) or {}
    prior_rows = {
        str(it.get("id") or "").strip(): it
        for it in (built_doc.get("items") or [])
        if isinstance(it, dict) and str(it.get("id") or "").strip()
    }
    out = prepare_approved_document(**parsed, auto_items=auto_items, prior_rows_by_id=prior_rows)
    out_path = s.data_root() / s.FREE_CLAIMS_APPROVED_PATH
    out_path.parent.mkdir(parents=True, exist_ok=True)
    safe_write_text(
        out_path,
        json.dumps(out, indent=2, ensure_ascii=False),
    )
    s._send_json(handler, HTTPStatus.OK, {"ok": True, "ids": len(out.get("ids") or [])})


def _admin_sponsors_path(s):
    """Profile-scoped sponsors.json for the app; BAKLOG_SPONSORS_INPUT overrides."""
    import os

    if os.environ.get("BAKLOG_SPONSORS_INPUT", "").strip():
        return s._resolve_contained_data_path(s.SPONSORS_PATH)
    return s.sponsors_path()


def handle_internal_sponsors_get(handler: SimpleHTTPRequestHandler) -> None:
    s = _srv()
    path = _admin_sponsors_path(s)
    if path is None:
        s._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "invalid sponsors input path"})
        return
    s._send_json(
        handler,
        HTTPStatus.OK,
        {
            "input": s._read_optional_json(path) or {"items": []},
        },
    )


def handle_internal_sponsors_put(handler: SimpleHTTPRequestHandler) -> None:
    s = _srv()
    from shared.safe_write import safe_write_text
    from shared.sponsors_validate import validate_sponsors_payload

    payload, err = s._read_json_body(handler)
    if err:
        s._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": err})
        return
    assert payload is not None
    validation_err = validate_sponsors_payload(payload)
    if validation_err:
        s._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": validation_err})
        return
    out_path = _admin_sponsors_path(s)
    if out_path is None:
        s._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "invalid sponsors input path"})
        return
    out_path.parent.mkdir(parents=True, exist_ok=True)
    safe_write_text(
        out_path,
        json.dumps(payload, indent=2, ensure_ascii=False),
    )
    if payload.get("version") == 2:
        count = len(payload.get("ads") or {})
    else:
        count = len(payload.get("items") or [])
    s._send_json(handler, HTTPStatus.OK, {"ok": True, "items": count, "ads": count})
