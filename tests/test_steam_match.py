"""Tests for shared/steam_match.py — Steam title matching helpers."""

from __future__ import annotations

from shared.steam_match import (
    appid_from_steam_url,
    close_enough_title,
    normalize_title,
    pick_appid,
    strip_giveaway_decorations,
)


def test_strip_giveaway_decorations_steam_suffix() -> None:
    raw = "Remothered: Tormented Fathers (Steam) Giveaway"
    assert strip_giveaway_decorations(raw) == "Remothered: Tormented Fathers"


def test_strip_giveaway_decorations_trailing_giveaway() -> None:
    assert strip_giveaway_decorations("Some Game Giveaway") == "Some Game"


def test_appid_from_steam_url() -> None:
    assert appid_from_steam_url("https://store.steampowered.com/app/12345/Game/") == 12345
    assert appid_from_steam_url("https://www.gamerpower.com/open/foo") is None


def test_pick_appid_exact_match() -> None:
    items = [{"id": 42, "name": "Portal 2"}]
    assert pick_appid(items, "Portal 2") == 42


def test_pick_appid_close_enough() -> None:
    items = [{"id": 99, "name": "Control Ultimate Edition"}]
    assert pick_appid(items, "Control") == 99


def test_pick_appid_rejects_sequel() -> None:
    items = [{"id": 2, "name": "Death Stranding 2 On The Beach"}]
    assert pick_appid(items, "Death Stranding") is None


def test_close_enough_title_sequel_guard() -> None:
    assert close_enough_title(
        normalize_title("death stranding"),
        normalize_title("death stranding 2 on beach"),
    ) is False
    assert close_enough_title(
        normalize_title("death stranding 2"),
        normalize_title("death stranding 2 on beach"),
    ) is True
