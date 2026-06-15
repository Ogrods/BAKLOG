"""Tests for the per-endpoint cache TTL added to GogClient._read_cache."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from clients.gog_client import GogClient


@pytest.fixture()
def client(tmp_path: Path) -> GogClient:
    return GogClient(gog_al="dummy", cache_dir=tmp_path / "gog")


def _write(client: GogClient, key: str, payload: dict) -> Path:
    client.cache_dir.mkdir(parents=True, exist_ok=True)
    path = client._cache_path(key)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_read_cache_returns_payload_when_no_ttl(client: GogClient):
    _write(client, "k", {"hello": "world"})
    assert client._read_cache("k") == {"hello": "world"}


def test_read_cache_returns_none_when_ttl_zero(client: GogClient):
    _write(client, "k", {"hello": "world"})
    assert client._read_cache("k", max_age_seconds=0) is None


def test_read_cache_respects_ttl(client: GogClient):
    path = _write(client, "k", {"hello": "world"})
    aged = time.time() - 120
    os.utime(path, (aged, aged))
    assert client._read_cache("k", max_age_seconds=60) is None
    assert client._read_cache("k", max_age_seconds=600) == {"hello": "world"}


def test_read_cache_missing_file_returns_none(client: GogClient):
    assert client._read_cache("nope") is None
    assert client._read_cache("nope", max_age_seconds=10) is None


def test_read_cache_handles_corruption(client: GogClient):
    path = client._cache_path("k")
    client.cache_dir.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert client._read_cache("k") is None
