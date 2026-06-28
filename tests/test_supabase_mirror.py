"""Tests for shared/supabase_mirror.py helpers."""

from __future__ import annotations

import pytest

from shared import supabase_mirror as sm


def test_mirror_object_key():
    assert sm.mirror_object_key("uid", "prof", "games_steam.json") == "uid/prof/games_steam.json"
    assert sm.mirror_object_key("uid", "prof", "data/personal.json") == "uid/prof/data/personal.json"


def test_mirror_object_key_rejects_traversal():
    with pytest.raises(ValueError, match="invalid artifact path"):
        sm.mirror_object_key("uid", "prof", "../secrets.bin")


def test_mirror_object_key_requires_parts():
    with pytest.raises(ValueError, match="invalid mirror object key parts"):
        sm.mirror_object_key("", "prof", "games_steam.json")
