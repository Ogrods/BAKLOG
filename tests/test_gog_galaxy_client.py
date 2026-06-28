"""Tests for gog_galaxy_client.py (minimal galaxy-2.0.db fixture)."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

from clients.gog_galaxy_client import GogGalaxyClient, GogGalaxyError, default_galaxy_db


def _seed_galaxy_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE GamePieceTypes (id INTEGER PRIMARY KEY, type TEXT);
            INSERT INTO GamePieceTypes (id, type) VALUES
                (23, 'title'),
                (8, 'originalImages'),
                (9, 'originalMeta');

            CREATE TABLE ProductPurchaseDates (
                gameReleaseKey TEXT,
                purchaseDate TEXT
            );
            INSERT INTO ProductPurchaseDates VALUES
                ('gog_1001', '2020-05-01T00:00:00'),
                ('steam_999', '2020-05-01T00:00:00');

            CREATE TABLE GamePieces (
                releaseKey TEXT,
                gamePieceTypeId INTEGER,
                value TEXT
            );
            INSERT INTO GamePieces VALUES
                ('gog_1001', 23, 'Test GOG Game'),
                ('gog_1001', 8, '{"background":"https://images.gog.com/bg.jpg"}'),
                ('gog_1001', 9, '{"slug":"test-gog-game","genres":["RPG"],"releaseDate":1527552000}'),
                ('steam_999', 23, '"Steam Only"');
            """
        )
        conn.commit()
    finally:
        conn.close()


def test_get_library_records_gog_only(tmp_path: Path) -> None:
    db = tmp_path / "galaxy-2.0.db"
    _seed_galaxy_db(db)
    records = GogGalaxyClient(db).get_library_records()
    assert len(records) == 1
    assert records[0]["gog_id"] == 1001
    assert records[0]["name"] == "Test GOG Game"
    assert records[0]["header_image"] == "https://images.gog.com/bg.jpg"
    assert records[0]["store_url"] == "https://www.gog.com/game/test-gog-game"
    assert records[0]["genres"] == ["RPG"]
    # release_date is the real game release (meta.releaseDate, Unix seconds),
    # NOT the user's purchase date from ProductPurchaseDates.
    assert records[0]["release_date"] == "2018-05-29"


def _seed_galaxy_db_with_dlc(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE GamePieceTypes (id INTEGER PRIMARY KEY, type TEXT);
            INSERT INTO GamePieceTypes (id, type) VALUES
                (23, 'title'),
                (10, 'parent');

            CREATE TABLE ProductPurchaseDates (gameReleaseKey TEXT, purchaseDate TEXT);
            INSERT INTO ProductPurchaseDates VALUES
                ('gog_2002', '2021-01-01T00:00:00'),
                ('gog_2003', '2021-06-01T00:00:00');

            CREATE TABLE GamePieces (
                releaseKey TEXT, gamePieceTypeId INTEGER, value TEXT
            );
            INSERT INTO GamePieces VALUES
                ('gog_2002', 23, 'Base Game'),
                ('gog_2003', 23, 'Expansion Pack'),
                ('gog_2003', 10, '{"parentGrk":"gog_2002"}');
            """
        )
        conn.commit()
    finally:
        conn.close()


def test_skips_dlc_with_parent_piece(tmp_path: Path) -> None:
    db = tmp_path / "galaxy-2.0.db"
    _seed_galaxy_db_with_dlc(db)
    records = GogGalaxyClient(db).get_library_records()
    assert len(records) == 1
    assert records[0]["gog_id"] == 2002
    assert records[0]["name"] == "Base Game"


def test_missing_db_raises(tmp_path: Path) -> None:
    with pytest.raises(GogGalaxyError, match="not found"):
        GogGalaxyClient(tmp_path / "missing.db").get_library_records()


def _seed_galaxy_db_with_luna_dupes(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE GamePieceTypes (id INTEGER PRIMARY KEY, type TEXT);
            INSERT INTO GamePieceTypes (id, type) VALUES (23, 'title');

            CREATE TABLE ProductPurchaseDates (gameReleaseKey TEXT, purchaseDate TEXT);
            INSERT INTO ProductPurchaseDates VALUES
                ('gog_3001', '2021-01-01T00:00:00'),
                ('gog_3002', '2021-01-01T00:00:00'),
                ('gog_3003', '2021-01-01T00:00:00');

            CREATE TABLE GamePieces (
                releaseKey TEXT, gamePieceTypeId INTEGER, value TEXT
            );
            INSERT INTO GamePieces VALUES
                ('gog_3001', 23, 'Ashworld'),
                ('gog_3002', 23, 'Ashworld - Amazon Luna'),
                ('gog_3003', 23, 'Brigador: Up-Armored Deluxe - Amazon Luna');
            """
        )
        conn.commit()
    finally:
        conn.close()


def test_collapses_amazon_luna_dupes(tmp_path: Path) -> None:
    db = tmp_path / "galaxy-2.0.db"
    _seed_galaxy_db_with_luna_dupes(db)
    records = GogGalaxyClient(db).get_library_records()
    names = {r["name"] for r in records}
    assert names == {"Ashworld", "Brigador: Up-Armored Deluxe"}
    assert len(records) == 2
    gog_ids = {r["gog_id"] for r in records}
    assert gog_ids == {3001, 3003}
    assert not any("Amazon Luna" in (r.get("name") or "") for r in records)


def _seed_galaxy_db_with_prime_dupes(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE GamePieceTypes (id INTEGER PRIMARY KEY, type TEXT);
            INSERT INTO GamePieceTypes (id, type) VALUES (23, 'title');

            CREATE TABLE ProductPurchaseDates (gameReleaseKey TEXT, purchaseDate TEXT);
            INSERT INTO ProductPurchaseDates VALUES
                ('gog_4001', '2021-01-01T00:00:00'),
                ('gog_4002', '2021-01-01T00:00:00'),
                ('gog_4003', '2021-01-01T00:00:00');

            CREATE TABLE GamePieces (
                releaseKey TEXT, gamePieceTypeId INTEGER, value TEXT
            );
            INSERT INTO GamePieces VALUES
                ('gog_4001', 23, 'Berserk Boy'),
                ('gog_4002', 23, 'Berserk Boy - Amazon Prime'),
                ('gog_4003', 23, 'Silver Box Classics - Amazon Prime');
            """
        )
        conn.commit()
    finally:
        conn.close()


def test_collapses_amazon_prime_dupes(tmp_path: Path) -> None:
    db = tmp_path / "galaxy-2.0.db"
    _seed_galaxy_db_with_prime_dupes(db)
    records = GogGalaxyClient(db).get_library_records()
    names = {r["name"] for r in records}
    assert names == {"Berserk Boy", "Silver Box Classics"}
    assert len(records) == 2
    assert not any("Amazon Prime" in (r.get("name") or "") for r in records)


def _seed_galaxy_db_with_dlcs_list(path: Path) -> None:
    """Base game whose ``dlcs`` piece lists an owned add-on that has no parent piece."""
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE GamePieceTypes (id INTEGER PRIMARY KEY, type TEXT);
            INSERT INTO GamePieceTypes (id, type) VALUES
                (23, 'title'),
                (40, 'dlcs');

            CREATE TABLE ProductPurchaseDates (gameReleaseKey TEXT, purchaseDate TEXT);
            INSERT INTO ProductPurchaseDates VALUES
                ('gog_5001', '2021-01-01T00:00:00'),
                ('gog_5002', '2021-01-01T00:00:00'),
                ('gog_5003', '2021-01-01T00:00:00'),
                ('gog_5004', '2021-01-01T00:00:00');

            CREATE TABLE GamePieces (
                releaseKey TEXT, gamePieceTypeId INTEGER, value TEXT
            );
            INSERT INTO GamePieces VALUES
                ('gog_5001', 23, 'Base Game'),
                ('gog_5001', 40, '{"dlcs":["gog_5002"]}'),
                ('gog_5002', 23, 'Vicious Soundtrack'),
                ('gog_5003', 23, 'Some Deluxe DLC Upgrade'),
                ('gog_5004', 23, 'Freedom to buy games');
            """
        )
        conn.commit()
    finally:
        conn.close()


def _seed_galaxy_db_with_silver_box_pack(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE GamePieceTypes (id INTEGER PRIMARY KEY, type TEXT);
            INSERT INTO GamePieceTypes (id, type) VALUES (23, 'title');

            CREATE TABLE ProductPurchaseDates (gameReleaseKey TEXT, purchaseDate TEXT);
            INSERT INTO ProductPurchaseDates VALUES
                ('gog_6001', '2021-01-01T00:00:00'),
                ('gog_6002', '2021-01-01T00:00:00'),
                ('gog_6003', '2021-01-01T00:00:00'),
                ('gog_6004', '2021-01-01T00:00:00'),
                ('gog_6005', '2021-01-01T00:00:00');

            CREATE TABLE GamePieces (
                releaseKey TEXT, gamePieceTypeId INTEGER, value TEXT
            );
            INSERT INTO GamePieces VALUES
                ('gog_6001', 23, 'Silver Box Classics'),
                ('gog_6002', 23, 'Heroes of the Lance'),
                ('gog_6003', 23, 'Dragons of Flame'),
                ('gog_6004', 23, 'War of the Lance'),
                ('gog_6005', 23, 'Shadow Sorcerer');
            """
        )
        conn.commit()
    finally:
        conn.close()


def test_drops_pack_when_all_components_owned(tmp_path: Path) -> None:
    db = tmp_path / "galaxy-2.0.db"
    _seed_galaxy_db_with_silver_box_pack(db)
    records = GogGalaxyClient(db).get_library_records()
    names = {r["name"] for r in records}
    assert "Silver Box Classics" not in names
    assert names == {
        "Heroes of the Lance",
        "Dragons of Flame",
        "War of the Lance",
        "Shadow Sorcerer",
    }


def _seed_galaxy_db_with_fr_collection_one(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE GamePieceTypes (id INTEGER PRIMARY KEY, type TEXT);
            INSERT INTO GamePieceTypes (id, type) VALUES (23, 'title');

            CREATE TABLE ProductPurchaseDates (gameReleaseKey TEXT, purchaseDate TEXT);
            INSERT INTO ProductPurchaseDates VALUES
                ('gog_7001', '2021-01-01T00:00:00'),
                ('gog_7002', '2021-01-01T00:00:00'),
                ('gog_7003', '2021-01-01T00:00:00'),
                ('gog_7004', '2021-01-01T00:00:00');

            CREATE TABLE GamePieces (
                releaseKey TEXT, gamePieceTypeId INTEGER, value TEXT
            );
            INSERT INTO GamePieces VALUES
                ('gog_7001', 23, 'Forgotten Realms: The Archives - Collection One'),
                ('gog_7002', 23, 'Eye of the Beholder'),
                ('gog_7003', 23, 'Eye of the Beholder II: The Legend of Darkmoon'),
                ('gog_7004', 23, 'Eye of the Beholder III: Assault on Myth Drannor');
            """
        )
        conn.commit()
    finally:
        conn.close()


def test_drops_forgotten_realms_collection_one(tmp_path: Path) -> None:
    db = tmp_path / "galaxy-2.0.db"
    _seed_galaxy_db_with_fr_collection_one(db)
    records = GogGalaxyClient(db).get_library_records()
    names = {r["name"] for r in records}
    assert "Forgotten Realms: The Archives - Collection One" not in names
    assert len(names) == 3


def _seed_galaxy_db_with_product_links_pack(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE GamePieceTypes (id INTEGER PRIMARY KEY, type TEXT);
            INSERT INTO GamePieceTypes (id, type) VALUES
                (23, 'title'),
                (50, 'productLinks');

            CREATE TABLE ProductPurchaseDates (gameReleaseKey TEXT, purchaseDate TEXT);
            INSERT INTO ProductPurchaseDates VALUES
                ('gog_8001', '2021-01-01T00:00:00'),
                ('gog_8002', '2021-01-01T00:00:00'),
                ('gog_8003', '2021-01-01T00:00:00');

            CREATE TABLE GamePieces (
                releaseKey TEXT, gamePieceTypeId INTEGER, value TEXT
            );
            INSERT INTO GamePieces VALUES
                ('gog_8001', 23, 'Data-Driven Bundle'),
                ('gog_8001', 50, '{"links":[{"releaseKey":"gog_8002"},{"releaseKey":"gog_8003"}]}'),
                ('gog_8002', 23, 'Component A'),
                ('gog_8003', 23, 'Component B');
            """
        )
        conn.commit()
    finally:
        conn.close()


def test_drops_pack_when_productlinks_components_owned(tmp_path: Path) -> None:
    db = tmp_path / "galaxy-2.0.db"
    _seed_galaxy_db_with_product_links_pack(db)
    records = GogGalaxyClient(db).get_library_records()
    names = {r["name"] for r in records}
    assert names == {"Component A", "Component B"}


def test_library_releases_fallback_when_no_purchase_dates(tmp_path: Path) -> None:
    db = tmp_path / "galaxy-2.0.db"
    conn = sqlite3.connect(db)
    try:
        conn.executescript(
            """
            CREATE TABLE GamePieceTypes (id INTEGER PRIMARY KEY, type TEXT);
            INSERT INTO GamePieceTypes (id, type) VALUES (23, 'title');

            CREATE TABLE LibraryReleases (releaseKey TEXT);
            INSERT INTO LibraryReleases VALUES ('gog_9001');

            CREATE TABLE GamePieces (
                releaseKey TEXT, gamePieceTypeId INTEGER, value TEXT
            );
            INSERT INTO GamePieces VALUES ('gog_9001', 23, 'Library Release Game');
            """
        )
        conn.commit()
    finally:
        conn.close()
    records = GogGalaxyClient(db).get_library_records()
    assert len(records) == 1
    assert records[0]["name"] == "Library Release Game"


def test_skips_dlcs_listed_and_keeps_name_noise_titles(tmp_path: Path) -> None:
    db = tmp_path / "galaxy-2.0.db"
    _seed_galaxy_db_with_dlcs_list(db)
    records = GogGalaxyClient(db).get_library_records()
    names = {r["name"] for r in records}
    # gog_5002 dropped (base game's dlcs list). Name-DLC + voucher rows are kept
    # for fetch_gog to tag as library noise.
    assert names == {"Base Game", "Some Deluxe DLC Upgrade", "Freedom to buy games"}
    assert {r["gog_id"] for r in records} == {5001, 5003, 5004}


def test_default_galaxy_db_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    path = default_galaxy_db()
    assert path.name == "galaxy-2.0.db"
    assert "GOG.com" in str(path)


def test_default_galaxy_db_darwin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    path = default_galaxy_db()
    assert path == Path("/Users/Shared/GOG.com/Galaxy/Storage/galaxy-2.0.db")


def test_default_galaxy_db_linux_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(GogGalaxyError, match="Windows/macOS only"):
        default_galaxy_db()
