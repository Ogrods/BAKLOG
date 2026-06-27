"""Regression smoke: fetcher registry + auth platform matrix."""

from __future__ import annotations

import importlib
import sys

import pytest

from auth.registry import PROVIDERS
from fetchers.registry import entries_by_key
from shared.platform_support import platform_supported


def test_manifest_loads_all_fetcher_scripts() -> None:
    entries = entries_by_key()
    assert len(entries) >= 20
    for key, entry in entries.items():
        script = entry.get("script")
        assert script, f"{key} missing script"
        module_name = script.replace("/", ".").removesuffix(".py")
        mod = importlib.import_module(module_name)
        assert callable(getattr(mod, "main", None)), f"{key} missing main()"


def test_amazon_launcher_blocked_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    import fetchers.fetch_amazon as fetch_amazon

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(fetch_amazon, "resolve_source", lambda *_a, **_k: "launcher")
    monkeypatch.setattr(sys, "argv", ["fetch_amazon", "--source", "launcher"])
    assert fetch_amazon.main() == 1


def test_gog_galaxy_supported_on_darwin() -> None:
    gog = PROVIDERS["gog_galaxy"]
    assert "darwin" in gog.platforms


def test_browser_providers_available_everywhere() -> None:
    for key in ("steam", "epic", "gog"):
        provider = PROVIDERS[key]
        assert provider.platforms == () or platform_supported(provider.platforms)
