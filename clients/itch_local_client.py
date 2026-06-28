import os
import sqlite3
import sys
from pathlib import Path

BUTLER_DB = "butler.db"


class ItchLocalError(Exception):
    pass


def default_butler_db():
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", "")) / "itch"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "itch"
        return base / "db" / BUTLER_DB
    else:
        modern = Path.home() / ".local" / "share" / "itch" / "db" / BUTLER_DB
        if modern.is_file():
            return modern
        base = Path.home() / ".config" / "itch"
    return base / "db" / BUTLER_DB


def _table_columns(conn, table):
    try:
        return {str(row[1]).lower() for row in conn.execute(f"PRAGMA table_info({table})")}
    except sqlite3.Error:
        return set()


def _first_col(cols, *candidates):
    for c in candidates:
        if c.lower() in cols:
            return c
    return None


def _iso_date(raw):
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text.startswith("0001-01-01"):
        return None
    return text[:10] if len(text) >= 10 else text


class ItchLocalClient:
    def __init__(self, db_path=None):
        self.db_path = Path(db_path) if db_path else default_butler_db()
        if not self.db_path.is_file():
            raise ItchLocalError(
                f"itch app database not found:\n  {self.db_path}\nInstall the itch desktop app, sign in, and open your library once."
            )

    def _connect_ro(self):
        return sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)

    def _table_exists(self, conn, name):
        row = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (name,)).fetchone()
        return row is not None

    def _load_cave_stats(self, conn):
        if not self._table_exists(conn, "caves"):
            return {}
        cols = _table_columns(conn, "caves")
        game_col = _first_col(cols, "game_id", "gameId")
        if not game_col:
            return {}
        touched_col = _first_col(cols, "last_touched_at", "lastTouchedAt")
        seconds_col = _first_col(cols, "seconds_run", "secondsRun")
        select = [game_col]
        if touched_col:
            select.append(touched_col)
        if seconds_col:
            select.append(seconds_col)
        sql = f"SELECT {', '.join(select)} FROM caves"
        out = {}
        for row in conn.execute(sql):
            try:
                gid = int(row[0])
            except (TypeError, ValueError):
                continue
            stats = {}
            idx = 1
            if touched_col:
                stats["last_played"] = _iso_date(row[idx])
                idx += 1
            if seconds_col and len(row) > idx:
                try:
                    secs = int(row[idx] or 0)
                except (TypeError, ValueError):
                    secs = 0
                stats["playtime_minutes"] = secs // 60 if secs > 0 else 0
            if stats:
                prev = out.get(gid)
                if prev is None:
                    out[gid] = stats
                else:
                    lp = stats.get("last_played")
                    if lp and (not prev.get("last_played") or lp > prev["last_played"]):
                        prev["last_played"] = lp
                    prev["playtime_minutes"] = max(
                        prev.get("playtime_minutes") or 0, stats.get("playtime_minutes") or 0
                    )
        return out

    def get_library_records(self):
        conn = self._connect_ro()
        conn.row_factory = sqlite3.Row
        try:
            if not self._table_exists(conn, "download_keys"):
                raise ItchLocalError("butler.db has no download_keys table.")
            if not self._table_exists(conn, "games"):
                raise ItchLocalError("butler.db has no games table.")
            dk_cols = _table_columns(conn, "download_keys")
            g_cols = _table_columns(conn, "games")
            dk_id = _first_col(dk_cols, "id") or "id"
            dk_game = _first_col(dk_cols, "game_id", "gameId") or "game_id"
            g_id = _first_col(g_cols, "id") or "id"
            g_title = _first_col(g_cols, "title") or "title"
            g_cover = _first_col(g_cols, "cover_url", "still_cover_url")
            g_url = _first_col(g_cols, "url")
            g_class = _first_col(g_cols, "classification")
            g_pub = _first_col(g_cols, "published_at", "created_at")
            g_short = _first_col(g_cols, "short_text")
            g_min_price = _first_col(g_cols, "min_price")
            g_press = _first_col(g_cols, "in_press_system")
            game_select = [f"g.{g_id} AS game_id", f"g.{g_title} AS title"]
            if g_cover:
                game_select.append(f"g.{g_cover} AS cover_url")
            if g_url:
                game_select.append(f"g.{g_url} AS url")
            if g_class:
                game_select.append(f"g.{g_class} AS classification")
            if g_pub:
                game_select.append(f"g.{g_pub} AS published_at")
            if g_short:
                game_select.append(f"g.{g_short} AS short_text")
            if g_min_price:
                game_select.append(f"g.{g_min_price} AS min_price")
            if g_press:
                game_select.append(f"g.{g_press} AS in_press_system")
            sql = f"SELECT dk.{dk_id} AS download_key_id, dk.{dk_game} AS game_id, {', '.join(game_select)} FROM download_keys dk INNER JOIN games g ON g.{g_id} = dk.{dk_game}"
            cave_stats = self._load_cave_stats(conn)
            rows = list(conn.execute(sql))
        finally:
            conn.close()
        records = []
        seen_games = set()
        for row in rows:
            row_map = {k: row[k] for k in row.keys()}
            try:
                gid = int(row_map["game_id"])
            except (TypeError, ValueError, KeyError):
                continue
            if gid in seen_games:
                continue
            seen_games.add(gid)
            title = (row_map.get("title") or "Untitled").strip()
            cover = row_map.get("cover_url")
            stats = cave_stats.get(gid, {})
            records.append(
                {
                    "itch_id": gid,
                    "download_key_id": row_map.get("download_key_id"),
                    "name": title,
                    "header_image": cover,
                    "library_image": cover,
                    "store_url": row_map.get("url"),
                    "release_date": _iso_date(row_map.get("published_at")),
                    "classification": row_map.get("classification"),
                    "short_text": row_map.get("short_text"),
                    "min_price": row_map.get("min_price"),
                    "in_press_system": bool(row_map.get("in_press_system")),
                    "last_played": stats.get("last_played"),
                    "playtime_minutes": stats.get("playtime_minutes", 0),
                }
            )
        return sorted(records, key=lambda r: r["name"].lower())
