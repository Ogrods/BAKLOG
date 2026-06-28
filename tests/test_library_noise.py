from shared.library_noise import (
    catalog_game_count,
    edition_title_join_key,
    is_catalog_noise_row,
    is_nintendo_noise_row,
    maybe_tag_library_noise_row,
    should_auto_hide_by_title,
)


def test_streaming_and_voucher_titles_auto_hide():
    assert should_auto_hide_by_title("YouTube")
    assert should_auto_hide_by_title("Hulu")
    assert should_auto_hide_by_title("Freedom to buy games")


def test_nintendo_extras_auto_hide():
    assert should_auto_hide_by_title("Sonic Digital Art Book")
    assert should_auto_hide_by_title("Persona 5 Royal Picaro Set")


def test_real_games_stay_visible():
    assert not should_auto_hide_by_title("Wallpaper Engine")
    assert not should_auto_hide_by_title("Costume Quest")
    assert not should_auto_hide_by_title("Hades")
    assert not should_auto_hide_by_title("ARK: Ragnarok")


def test_edition_dedupe_key_not_noise():
    deluxe = edition_title_join_key("Samba de Amigo: Party Central Digital Deluxe Edition")
    base = edition_title_join_key("Samba de Amigo: Party Central")
    assert deluxe == base
    assert not should_auto_hide_by_title("Skyrim Special Edition")


def test_nintendo_dlc_without_app_is_noise():
    assert is_nintendo_noise_row({"name": "Bonus Pack", "tags": ["dlc"]})


def test_nintendo_dlc_with_app_is_not_noise_by_metadata():
    row = {"name": "Expansion", "tags": ["dlc"], "has_nx_application": True}
    assert not is_nintendo_noise_row(row)


def test_maybe_tag_library_noise_row():
    row = {"store": "epic", "name": "YouTube", "tags": []}
    assert maybe_tag_library_noise_row(row, "epic")
    assert row["tags"] == ["noise"]
    assert is_catalog_noise_row(row)


def test_catalog_game_count_excludes_noise():
    games = [{"name": "Hades", "tags": []}, {"name": "YouTube", "tags": ["noise"]}]
    assert catalog_game_count(games) == 1
