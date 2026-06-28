from __future__ import annotations
import os
import sqlite3
import sys
from pathlib import Path
import pytest
from clients.itch_local_client import ItchLocalClient, ItchLocalError, default_butler_db

def _seed_butler_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript("\n            CREATE TABLE games (\n                id INTEGER PRIMARY KEY,\n                title TEXT,\n                cover_url TEXT,\n                url TEXT,\n                classification TEXT,\n                published_at TEXT,\n                short_text TEXT,\n                min_price INTEGER\n            );\n            INSERT INTO games VALUES\n                (42, 'Local Itch Game', 'https://img.itch/cover.png',\n                 'https://dev.itch.io/local-game', 'game', '2021-03-15', 'A short blurb', 0);\n\n            CREATE TABLE download_keys (id INTEGER PRIMARY KEY, game_id INTEGER);\n            INSERT INTO download_keys VALUES (9001, 42);\n\n            CREATE TABLE caves (\n                game_id INTEGER,\n                last_touched_at TEXT,\n                seconds_run INTEGER\n            );\n            INSERT INTO caves VALUES (42, '2024-08-20T12:00:00Z', 3600);\n            ")
        conn.commit()
    finally:
        conn.close()

def test_get_library_records_with_cave_stats(tmp_path: Path) -> None:
    db = tmp_path / 'butler.db'
    _seed_butler_db(db)
    records = ItchLocalClient(db).get_library_records()
    assert len(records) == 1
    rec = records[0]
    assert rec['itch_id'] == 42
    assert rec['name'] == 'Local Itch Game'
    assert rec['download_key_id'] == 9001
    assert rec['last_played'] == '2024-08-20'
    assert rec['playtime_minutes'] == 60
    assert rec['store_url'] == 'https://dev.itch.io/local-game'

def test_missing_db_raises(tmp_path: Path) -> None:
    with pytest.raises(ItchLocalError, match='not found'):
        ItchLocalClient(tmp_path / 'missing.db').get_library_records()

def test_default_butler_db_windows_includes_itch_folder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.setenv('APPDATA', 'C:\\Users\\Test\\AppData\\Roaming')
    path = default_butler_db()
    expected = Path(os.environ['APPDATA']) / 'itch' / 'db' / 'butler.db'
    assert path == expected
    assert path.parts[-3:] == ('itch', 'db', 'butler.db')

def test_default_butler_db_darwin_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.setattr('clients.itch_local_client.Path.home', lambda: Path('/Users/testuser'))
    path = default_butler_db()
    assert path == Path('/Users/testuser/Library/Application Support/itch/db/butler.db')

def test_default_butler_db_linux_prefers_local_share(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, 'platform', 'linux')
    home = tmp_path / 'home'
    home.mkdir()
    modern = home / '.local' / 'share' / 'itch' / 'db'
    modern.mkdir(parents=True)
    db = modern / 'butler.db'
    db.write_text('', encoding='utf-8')
    monkeypatch.setattr('clients.itch_local_client.Path.home', lambda: home)
    assert default_butler_db() == db

def test_default_butler_db_linux_falls_back_to_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, 'platform', 'linux')
    home = tmp_path / 'home'
    home.mkdir()
    monkeypatch.setattr('clients.itch_local_client.Path.home', lambda: home)
    path = default_butler_db()
    assert path == home / '.config' / 'itch' / 'db' / 'butler.db'