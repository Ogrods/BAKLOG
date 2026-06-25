"""Tests for Nintendo VGC portal parsing and catalog diff helpers."""

from __future__ import annotations

import json

import pytest

from clients.nintendo_vgc import (
    NintendoVgcAuthError,
    NintendoVgcCaptureError,
    fetch_vgc_portal_html,
    map_vgc_view,
    parse_vgc_embedded_json,
    region_from_vgc_state,
    resolve_nintendo_icon_url,
    _merge_vgc_payload,
    _portal_html_has_vgc_data,
    _portal_html_looks_unsigned,
)
from scripts.probe_nintendo_vgc import diff_vgc_vs_catalog


SAMPLE_PORTAL_HTML = """
<html><body>
<div id="data" data-json="{&quot;idToken&quot;:&quot;tok-abc&quot;,&quot;savannaClientId&quot;:&quot;client-1&quot;,&quot;shopGraphQLApiUrl&quot;:&quot;https://example.test/graphql&quot;}"></div>
<div id="state" data-json="{&quot;lang&quot;:&quot;en-US&quot;,&quot;user&quot;:{&quot;country&quot;:&quot;US&quot;}}"></div>
</body></html>
"""


def test_parse_vgc_embedded_json() -> None:
    data, state = parse_vgc_embedded_json(SAMPLE_PORTAL_HTML)
    assert data["idToken"] == "tok-abc"
    assert data["shopGraphQLApiUrl"] == "https://example.test/graphql"
    assert state["lang"] == "en-US"


def test_parse_vgc_embedded_json_missing_data_raises() -> None:
    with pytest.raises(NintendoVgcCaptureError, match="missing embedded"):
        parse_vgc_embedded_json("<html><body>no data</body></html>")


def test_region_from_vgc_state_us() -> None:
    region = region_from_vgc_state({"user": {"country": "US"}})
    assert region["country"] == "US"
    assert region["shop_id"] == 1


def test_region_from_vgc_state_lang_fallback_gb() -> None:
    region = region_from_vgc_state({"lang": "en-GB"})
    assert region["country"] == "GB"
    assert region["shop_id"] == 3


def test_map_vgc_view_switch_and_dlc() -> None:
    base = map_vgc_view(
        {
            "id": "vgc-1",
            "applicationId": "0100abc",
            "applicationName": "Zelda™ Tears",
            "apparentPlatform": "NX",
            "hasNxApplication": True,
            "icon": {
                "url": "https://atum-img.test/i/c/abc_${size}",
                "sizes": [128, 256, 512],
            },
        }
    )
    assert base["application_id"] == "0100abc"
    assert base["name"] == "Zelda™ Tears"
    assert base["platform"] == "Nintendo Switch"
    assert base["icon_url"] == "https://atum-img.test/i/c/abc_512"
    assert base["icon_url_standard"] == "https://atum-img.test/i/c/abc_256"
    assert base["is_dlc"] is False

    dlc = map_vgc_view(
        {
            "applicationId": "dlc-1",
            "applicationName": "Expansion Pass",
            "hasNxAddOnContents": True,
        }
    )
    assert dlc["is_dlc"] is True


def test_resolve_nintendo_icon_url_expands_size_placeholder() -> None:
    url = "https://atum-img.test/i/c/abc_${size}"
    assert resolve_nintendo_icon_url(url, [128, 256, 512]) == (
        "https://atum-img.test/i/c/abc_256"
    )
    assert resolve_nintendo_icon_url(url, [128, 256, 512], prefer_large=True) == (
        "https://atum-img.test/i/c/abc_512"
    )


def test_map_vgc_view_exposes_entitlement_metadata() -> None:
    view = {
        "id": "vgc-1",
        "applicationId": "0100abc",
        "applicationName": "Zelda™ Tears",
        "apparentPlatform": "NX",
        "publisher": "Nintendo",
        "hasNxApplication": True,
        "hasApplication": True,
        "isLending": True,
        "containsReleased": True,
        "icon": {
            "url": "https://img.test/a_${size}",
            "upgradedIconUrl": "https://img.test/b_${size}",
            "sizes": [256, 512],
        },
    }
    mapped = map_vgc_view(view)
    assert mapped["icon_url"] == "https://img.test/b_512"
    assert mapped["icon_url_standard"] == "https://img.test/a_256"
    assert mapped["has_nx_application"] is True
    assert mapped["is_lending"] is True
    assert mapped["contains_released"] is True
    assert "raw" not in mapped


def test_merge_vgc_payload_dedupes_application_id() -> None:
    payload = {
        "data": {
            "account": {
                "vgc": {
                    "vgcViews": {
                        "views": [
                            {"applicationId": "a1", "applicationName": "One"},
                            {"applicationId": "a1", "applicationName": "One dup"},
                            {"applicationId": "a2", "applicationName": "Two"},
                        ]
                    }
                }
            }
        }
    }
    collected: list = []
    seen: set[str] = set()
    added = _merge_vgc_payload(payload, collected, seen)
    assert added == 2
    assert [r["application_id"] for r in collected] == ["a1", "a2"]


def test_portal_html_helpers() -> None:
    assert _portal_html_has_vgc_data(SAMPLE_PORTAL_HTML) is True
    assert _portal_html_looks_unsigned(SAMPLE_PORTAL_HTML) is False
    assert _portal_html_looks_unsigned("<html>Please sign in</html>") is True


def test_fetch_vgc_portal_html_via_http_get() -> None:
    class _Resp:
        status = 200

        def text(self) -> str:
            return SAMPLE_PORTAL_HTML

    class _Request:
        def get(self, url: str, *, headers: dict, timeout: float) -> _Resp:
            assert "accounts.nintendo.com" in url
            return _Resp()

    class _Ctx:
        request = _Request()

    html = fetch_vgc_portal_html(_Ctx(), user_agent="test-agent")
    assert "data-json" in html


def test_fetch_vgc_portal_html_unsigned_raises() -> None:
    class _Resp:
        status = 200

        def text(self) -> str:
            return "<html><body>Please sign in to continue</body></html>"

    class _Request:
        def get(self, url: str, *, headers: dict, timeout: float) -> _Resp:
            return _Resp()

    class _Ctx:
        request = _Request()

    with pytest.raises(NintendoVgcAuthError, match="session expired"):
        fetch_vgc_portal_html(_Ctx(), user_agent="test-agent")


def test_diff_vgc_vs_catalog_legacy_gap() -> None:
    vgc_rows = [
        {"name": "Fresh Game", "application_id": "app-1"},
        {"name": "Shared Title", "application_id": "app-2"},
    ]
    catalog = [
        {"name": "Shared Title", "id": "tx-1"},
        {"name": "Old Purchase", "id": "tx-2", "nintendo_legacy": True},
        {"name": "Receipt Only", "id": "tx-3"},
    ]
    summary = diff_vgc_vs_catalog(vgc_rows, catalog)
    assert summary["vgc_count"] == 2
    assert summary["catalog_count"] == 3
    assert "fresh game" in summary["only_vgc_titles"]
    assert "receipt only" in summary["only_catalog_titles"]
    assert summary["legacy_not_in_vgc_titles"] == ["Old Purchase"]
    assert summary["shared_title_count"] == 1
