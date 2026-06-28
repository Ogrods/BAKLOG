import sqlite3
import sys
from pathlib import Path

import pytest

from clients.gog_galaxy_client import GogGalaxyClient, GogGalaxyError, default_galaxy_db


def _seed_galaxy_db(path):
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            "\n            CREATE TABLE GamePieceTypes (id INTEGER PRIMARY KEY, type TEXT);\n            INSERT INTO GamePieceTypes (id, type) VALUES\n                (23, 'title'),\n                (8, 'originalImages'),\n                (9, 'originalMeta');\n\n            CREATE TABLE ProductPurchaseDates (\n                gameReleaseKey TEXT,\n                purchaseDate TEXT\n            );\n            INSERT INTO ProductPurchaseDates VALUES\n                ('gog_1001', '2020-05-01T00:00:00'),\n                ('steam_999', '2020-05-01T00:00:00');\n\n            CREATE TABLE GamePieces (\n                releaseKey TEXT,\n                gamePieceTypeId INTEGER,\n                value TEXT\n            );\n            INSERT INTO GamePieces VALUES\n                ('gog_1001', 23, 'Test GOG Game'),\n                ('gog_1001', 8, '{\"background\":\"https://images.gog.com/bg.jpg\"}'),\n                ('gog_1001', 9, '{\"slug\":\"test-gog-game\",\"genres\":[\"RPG\"],\"releaseDate\":1527552000}'),\n                ('steam_999', 23, '\"Steam Only\"');\n            "
        )
        conn.commit()
    finally:
        conn.close()


def test_get_library_records_gog_only(tmp_path):
    db = tmp_path / "galaxy-2.0.db"
    _seed_galaxy_db(db)
    records = GogGalaxyClient(db).get_library_records()
    assert len(records) == 1
    assert records[0]["gog_id"] == 1001
    assert records[0]["name"] == "Test GOG Game"
    assert records[0]["header_image"] == "https://images.gog.com/bg.jpg"
    assert records[0]["store_url"] == "https://www.gog.com/game/test-gog-game"
    assert records[0]["genres"] == ["RPG"]
    assert records[0]["release_date"] == "2018-05-29"


def _seed_galaxy_db_with_dlc(path):
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            "\n            CREATE TABLE GamePieceTypes (id INTEGER PRIMARY KEY, type TEXT);\n            INSERT INTO GamePieceTypes (id, type) VALUES\n                (23, 'title'),\n                (10, 'parent');\n\n            CREATE TABLE ProductPurchaseDates (gameReleaseKey TEXT, purchaseDate TEXT);\n            INSERT INTO ProductPurchaseDates VALUES\n                ('gog_2002', '2021-01-01T00:00:00'),\n                ('gog_2003', '2021-06-01T00:00:00');\n\n            CREATE TABLE GamePieces (\n                releaseKey TEXT, gamePieceTypeId INTEGER, value TEXT\n            );\n            INSERT INTO GamePieces VALUES\n                ('gog_2002', 23, 'Base Game'),\n                ('gog_2003', 23, 'Expansion Pack'),\n                ('gog_2003', 10, '{\"parentGrk\":\"gog_2002\"}');\n            "
        )
        conn.commit()
    finally:
        conn.close()


def test_skips_dlc_with_parent_piece(tmp_path):
    db = tmp_path / "galaxy-2.0.db"
    _seed_galaxy_db_with_dlc(db)
    records = GogGalaxyClient(db).get_library_records()
    assert len(records) == 1
    assert records[0]["gog_id"] == 2002
    assert records[0]["name"] == "Base Game"


def test_missing_db_raises(tmp_path):
    with pytest.raises(GogGalaxyError, match="not found"):
        GogGalaxyClient(tmp_path / "missing.db").get_library_records()


def _seed_galaxy_db_with_luna_dupes(path):
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            "\n            CREATE TABLE GamePieceTypes (id INTEGER PRIMARY KEY, type TEXT);\n            INSERT INTO GamePieceTypes (id, type) VALUES (23, 'title');\n\n            CREATE TABLE ProductPurchaseDates (gameReleaseKey TEXT, purchaseDate TEXT);\n            INSERT INTO ProductPurchaseDates VALUES\n                ('gog_3001', '2021-01-01T00:00:00'),\n                ('gog_3002', '2021-01-01T00:00:00'),\n                ('gog_3003', '2021-01-01T00:00:00');\n\n            CREATE TABLE GamePieces (\n                releaseKey TEXT, gamePieceTypeId INTEGER, value TEXT\n            );\n            INSERT INTO GamePieces VALUES\n                ('gog_3001', 23, 'Ashworld'),\n                ('gog_3002', 23, 'Ashworld - Amazon Luna'),\n                ('gog_3003', 23, 'Brigador: Up-Armored Deluxe - Amazon Luna');\n            "
        )
        conn.commit()
    finally:
        conn.close()


def test_collapses_amazon_luna_dupes(tmp_path):
    db = tmp_path / "galaxy-2.0.db"
    _seed_galaxy_db_with_luna_dupes(db)
    records = GogGalaxyClient(db).get_library_records()
    names = {r["name"] for r in records}
    assert names == {"Ashworld", "Brigador: Up-Armored Deluxe"}
    assert len(records) == 2
    gog_ids = {r["gog_id"] for r in records}
    assert gog_ids == {3001, 3003}
    assert not any(("Amazon Luna" in (r.get("name") or "") for r in records))


def _seed_galaxy_db_with_prime_dupes(path):
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            "\n            CREATE TABLE GamePieceTypes (id INTEGER PRIMARY KEY, type TEXT);\n            INSERT INTO GamePieceTypes (id, type) VALUES (23, 'title');\n\n            CREATE TABLE ProductPurchaseDates (gameReleaseKey TEXT, purchaseDate TEXT);\n            INSERT INTO ProductPurchaseDates VALUES\n                ('gog_4001', '2021-01-01T00:00:00'),\n                ('gog_4002', '2021-01-01T00:00:00'),\n                ('gog_4003', '2021-01-01T00:00:00');\n\n            CREATE TABLE GamePieces (\n                releaseKey TEXT, gamePieceTypeId INTEGER, value TEXT\n            );\n            INSERT INTO GamePieces VALUES\n                ('gog_4001', 23, 'Berserk Boy'),\n                ('gog_4002', 23, 'Berserk Boy - Amazon Prime'),\n                ('gog_4003', 23, 'Silver Box Classics - Amazon Prime');\n            "
        )
        conn.commit()
    finally:
        conn.close()


def test_collapses_amazon_prime_dupes(tmp_path):
    db = tmp_path / "galaxy-2.0.db"
    _seed_galaxy_db_with_prime_dupes(db)
    records = GogGalaxyClient(db).get_library_records()
    names = {r["name"] for r in records}
    assert names == {"Berserk Boy", "Silver Box Classics"}
    assert len(records) == 2
    assert not any(("Amazon Prime" in (r.get("name") or "") for r in records))


def _seed_galaxy_db_with_dlcs_list(path):
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            "\n            CREATE TABLE GamePieceTypes (id INTEGER PRIMARY KEY, type TEXT);\n            INSERT INTO GamePieceTypes (id, type) VALUES\n                (23, 'title'),\n                (40, 'dlcs');\n\n            CREATE TABLE ProductPurchaseDates (gameReleaseKey TEXT, purchaseDate TEXT);\n            INSERT INTO ProductPurchaseDates VALUES\n                ('gog_5001', '2021-01-01T00:00:00'),\n                ('gog_5002', '2021-01-01T00:00:00'),\n                ('gog_5003', '2021-01-01T00:00:00'),\n                ('gog_5004', '2021-01-01T00:00:00');\n\n            CREATE TABLE GamePieces (\n                releaseKey TEXT, gamePieceTypeId INTEGER, value TEXT\n            );\n            INSERT INTO GamePieces VALUES\n                ('gog_5001', 23, 'Base Game'),\n                ('gog_5001', 40, '{\"dlcs\":[\"gog_5002\"]}'),\n                ('gog_5002', 23, 'Vicious Soundtrack'),\n                ('gog_5003', 23, 'Some Deluxe DLC Upgrade'),\n                ('gog_5004', 23, 'Freedom to buy games');\n            "
        )
        conn.commit()
    finally:
        conn.close()


def _seed_galaxy_db_with_silver_box_pack(path):
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            "\n            CREATE TABLE GamePieceTypes (id INTEGER PRIMARY KEY, type TEXT);\n            INSERT INTO GamePieceTypes (id, type) VALUES (23, 'title');\n\n            CREATE TABLE ProductPurchaseDates (gameReleaseKey TEXT, purchaseDate TEXT);\n            INSERT INTO ProductPurchaseDates VALUES\n                ('gog_6001', '2021-01-01T00:00:00'),\n                ('gog_6002', '2021-01-01T00:00:00'),\n                ('gog_6003', '2021-01-01T00:00:00'),\n                ('gog_6004', '2021-01-01T00:00:00'),\n                ('gog_6005', '2021-01-01T00:00:00');\n\n            CREATE TABLE GamePieces (\n                releaseKey TEXT, gamePieceTypeId INTEGER, value TEXT\n            );\n            INSERT INTO GamePieces VALUES\n                ('gog_6001', 23, 'Silver Box Classics'),\n                ('gog_6002', 23, 'Heroes of the Lance'),\n                ('gog_6003', 23, 'Dragons of Flame'),\n                ('gog_6004', 23, 'War of the Lance'),\n                ('gog_6005', 23, 'Shadow Sorcerer');\n            "
        )
        conn.commit()
    finally:
        conn.close()


def test_drops_pack_when_all_components_owned(tmp_path):
    db = tmp_path / "galaxy-2.0.db"
    _seed_galaxy_db_with_silver_box_pack(db)
    records = GogGalaxyClient(db).get_library_records()
    names = {r["name"] for r in records}
    assert "Silver Box Classics" not in names
    assert names == {"Heroes of the Lance", "Dragons of Flame", "War of the Lance", "Shadow Sorcerer"}


def _seed_galaxy_db_with_fr_collection_one(path):
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            "\n            CREATE TABLE GamePieceTypes (id INTEGER PRIMARY KEY, type TEXT);\n            INSERT INTO GamePieceTypes (id, type) VALUES (23, 'title');\n\n            CREATE TABLE ProductPurchaseDates (gameReleaseKey TEXT, purchaseDate TEXT);\n            INSERT INTO ProductPurchaseDates VALUES\n                ('gog_7001', '2021-01-01T00:00:00'),\n                ('gog_7002', '2021-01-01T00:00:00'),\n                ('gog_7003', '2021-01-01T00:00:00'),\n                ('gog_7004', '2021-01-01T00:00:00');\n\n            CREATE TABLE GamePieces (\n                releaseKey TEXT, gamePieceTypeId INTEGER, value TEXT\n            );\n            INSERT INTO GamePieces VALUES\n                ('gog_7001', 23, 'Forgotten Realms: The Archives - Collection One'),\n                ('gog_7002', 23, 'Eye of the Beholder'),\n                ('gog_7003', 23, 'Eye of the Beholder II: The Legend of Darkmoon'),\n                ('gog_7004', 23, 'Eye of the Beholder III: Assault on Myth Drannor');\n            "
        )
        conn.commit()
    finally:
        conn.close()


def test_drops_forgotten_realms_collection_one(tmp_path):
    db = tmp_path / "galaxy-2.0.db"
    _seed_galaxy_db_with_fr_collection_one(db)
    records = GogGalaxyClient(db).get_library_records()
    names = {r["name"] for r in records}
    assert "Forgotten Realms: The Archives - Collection One" not in names
    assert len(names) == 3


def _seed_galaxy_db_with_product_links_pack(path):
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            "\n            CREATE TABLE GamePieceTypes (id INTEGER PRIMARY KEY, type TEXT);\n            INSERT INTO GamePieceTypes (id, type) VALUES\n                (23, 'title'),\n                (50, 'productLinks');\n\n            CREATE TABLE ProductPurchaseDates (gameReleaseKey TEXT, purchaseDate TEXT);\n            INSERT INTO ProductPurchaseDates VALUES\n                ('gog_8001', '2021-01-01T00:00:00'),\n                ('gog_8002', '2021-01-01T00:00:00'),\n                ('gog_8003', '2021-01-01T00:00:00');\n\n            CREATE TABLE GamePieces (\n                releaseKey TEXT, gamePieceTypeId INTEGER, value TEXT\n            );\n            INSERT INTO GamePieces VALUES\n                ('gog_8001', 23, 'Data-Driven Bundle'),\n                ('gog_8001', 50, '{\"links\":[{\"releaseKey\":\"gog_8002\"},{\"releaseKey\":\"gog_8003\"}]}'),\n                ('gog_8002', 23, 'Component A'),\n                ('gog_8003', 23, 'Component B');\n            "
        )
        conn.commit()
    finally:
        conn.close()


def test_drops_pack_when_productlinks_components_owned(tmp_path):
    db = tmp_path / "galaxy-2.0.db"
    _seed_galaxy_db_with_product_links_pack(db)
    records = GogGalaxyClient(db).get_library_records()
    names = {r["name"] for r in records}
    assert names == {"Component A", "Component B"}


def test_library_releases_fallback_when_no_purchase_dates(tmp_path):
    db = tmp_path / "galaxy-2.0.db"
    conn = sqlite3.connect(db)
    try:
        conn.executescript(
            "\n            CREATE TABLE GamePieceTypes (id INTEGER PRIMARY KEY, type TEXT);\n            INSERT INTO GamePieceTypes (id, type) VALUES (23, 'title');\n\n            CREATE TABLE LibraryReleases (releaseKey TEXT);\n            INSERT INTO LibraryReleases VALUES ('gog_9001');\n\n            CREATE TABLE GamePieces (\n                releaseKey TEXT, gamePieceTypeId INTEGER, value TEXT\n            );\n            INSERT INTO GamePieces VALUES ('gog_9001', 23, 'Library Release Game');\n            "
        )
        conn.commit()
    finally:
        conn.close()
    records = GogGalaxyClient(db).get_library_records()
    assert len(records) == 1
    assert records[0]["name"] == "Library Release Game"


def test_skips_dlcs_listed_and_keeps_name_noise_titles(tmp_path):
    db = tmp_path / "galaxy-2.0.db"
    _seed_galaxy_db_with_dlcs_list(db)
    records = GogGalaxyClient(db).get_library_records()
    names = {r["name"] for r in records}
    assert names == {"Base Game", "Some Deluxe DLC Upgrade", "Freedom to buy games"}
    assert {r["gog_id"] for r in records} == {5001, 5003, 5004}


def test_default_galaxy_db_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    path = default_galaxy_db()
    assert path.name == "galaxy-2.0.db"
    assert "GOG.com" in str(path)


def test_default_galaxy_db_darwin(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    path = default_galaxy_db()
    assert path == Path("/Users/Shared/GOG.com/Galaxy/Storage/galaxy-2.0.db")


def test_default_galaxy_db_linux_raises(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(GogGalaxyError, match="Windows/macOS only"):
        default_galaxy_db()
