"""Tests for itch_game.py classification helper."""

from __future__ import annotations

from clients.itch_game import ITCH_NON_GAME_CLASSIFICATIONS, itch_is_videogame


def test_asset_pack_is_not_videogame() -> None:
    assert "asset_pack" in ITCH_NON_GAME_CLASSIFICATIONS
    assert not itch_is_videogame({"classification": "asset_pack"})


def test_game_and_empty_are_videogames() -> None:
    assert itch_is_videogame({"classification": "game"})
    assert itch_is_videogame({})
    assert itch_is_videogame({"classification": ""})


def test_tool_is_not_videogame() -> None:
    assert not itch_is_videogame({"classification": "tool"})
