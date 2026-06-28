import json
import re
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

from .gog_filters import apply_gog_name_filters

GALAXY_DB_NAME = "galaxy-2.0.db"
_WIN_DB = Path("C:\\ProgramData\\GOG.com\\Galaxy\\storage") / GALAXY_DB_NAME
_DARWIN_DB = Path("/Users/Shared/GOG.com/Galaxy/Storage") / GALAXY_DB_NAME
_GOG_RELEASE_RE = re.compile("^gog_(\\d+)", re.IGNORECASE)


class GogGalaxyError(Exception):
    pass


def default_galaxy_db():
    if sys.platform == "win32":
        return _WIN_DB
    if sys.platform == "darwin":
        return _DARWIN_DB
    raise GogGalaxyError("GOG Galaxy is Windows/macOS only — use the GOG (web) source on Linux")


def _gog_id_from_release_key(release_key):
    m = _GOG_RELEASE_RE.match((release_key or "").strip())
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _parse_json_value(raw):
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    if text[0] in "{[":
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    return text


def _pick_cover_url(images_val):
    if isinstance(images_val, str) and images_val.startswith("http"):
        return images_val
    if not isinstance(images_val, dict):
        return None
    for key in ("background", "squareIcon", "squareIconGray", "logo", "icon", "cover"):
        url = images_val.get(key)
        if isinstance(url, str) and url.startswith("http"):
            return url
    for url in images_val.values():
        if isinstance(url, str) and url.startswith("http"):
            return url
    return None


def _meta_store_url(meta, gog_id):
    if isinstance(meta, dict):
        slug = meta.get("slug") or meta.get("gameSlug")
        if slug:
            return f"https://www.gog.com/game/{slug}"
        link = meta.get("link") or meta.get("url")
        if isinstance(link, str) and link.startswith("http"):
            return link
    return f"https://www.gog.com/en/game/{gog_id}"


def _release_date_from_meta(meta):
    if not isinstance(meta, dict):
        return None
    raw = meta.get("releaseDate")
    if raw is None:
        return None
    try:
        ts = int(raw)
    except (TypeError, ValueError):
        return None
    if ts <= 0:
        return None
    try:
        return datetime.fromtimestamp(ts, tz=UTC).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _genres_from_meta(meta):
    if not isinstance(meta, dict):
        return []
    out = []
    for key in ("genres", "tags", "genre"):
        raw = meta.get(key)
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, str) and item.strip():
                    out.append(item.strip())
                elif isinstance(item, dict):
                    label = item.get("name") or item.get("title")
                    if label:
                        out.append(str(label))
        elif isinstance(raw, str) and raw.strip():
            out.append(raw.strip())
    return list(dict.fromkeys(out))


class GogGalaxyClient:
    def __init__(self, db_path=None):
        self.db_path = Path(db_path) if db_path else default_galaxy_db()
        if not self.db_path.is_file():
            raise GogGalaxyError(
                f"GOG Galaxy database not found:\n  {self.db_path}\nInstall GOG Galaxy, sign in, and sync your library once."
            )

    def _connect_ro(self):
        return sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)

    def _table_exists(self, conn, name):
        row = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (name,)).fetchone()
        return row is not None

    def _load_type_ids(self, conn):
        if not self._table_exists(conn, "GamePieceTypes"):
            return {}
        out = {}
        for row_id, type_name in conn.execute("SELECT id, type FROM GamePieceTypes"):
            if type_name:
                out[str(type_name).strip().lower()] = int(row_id)
        return out

    def _owned_release_keys(self, conn):
        if self._table_exists(conn, "ProductPurchaseDates"):
            rows = conn.execute(
                "SELECT DISTINCT gameReleaseKey FROM ProductPurchaseDates WHERE gameReleaseKey LIKE 'gog\\_%' ESCAPE '\\'"
            ).fetchall()
            keys = [str(r[0]) for r in rows if r and r[0]]
            if keys:
                return keys
        if self._table_exists(conn, "LibraryReleases"):
            rows = conn.execute(
                "SELECT DISTINCT releaseKey FROM LibraryReleases WHERE releaseKey LIKE 'gog\\_%' ESCAPE '\\'"
            ).fetchall()
            return [str(r[0]) for r in rows if r and r[0]]
        raise GogGalaxyError("GOG Galaxy database has no ProductPurchaseDates or LibraryReleases table.")

    def _load_pieces_for_keys(self, conn, release_keys, type_ids):
        if not release_keys or not self._table_exists(conn, "GamePieces"):
            return {}
        title_id = type_ids.get("title")
        images_id = type_ids.get("originalimages") or type_ids.get("images")
        meta_id = type_ids.get("originalmeta") or type_ids.get("meta")
        wanted = {tid for tid in (title_id, images_id, meta_id) if tid is not None}
        if not wanted:
            return {}
        placeholders = ",".join("?" * len(release_keys))
        id_placeholders = ",".join("?" * len(wanted))
        sql = f"SELECT releaseKey, gamePieceTypeId, value FROM GamePieces WHERE releaseKey IN ({placeholders}) AND gamePieceTypeId IN ({id_placeholders})"
        by_key = {}
        for release_key, piece_type_id, value in conn.execute(sql, [*release_keys, *sorted(wanted)]):
            rk = str(release_key)
            bucket = by_key.setdefault(rk, {})
            parsed = _parse_json_value(value)
            tid = int(piece_type_id)
            if title_id is not None and tid == title_id:
                if isinstance(parsed, str):
                    title_text = parsed.strip()
                    if len(title_text) >= 2 and title_text[0] == title_text[-1] == '"':
                        try:
                            title_text = json.loads(title_text)
                        except json.JSONDecodeError:
                            title_text = title_text.strip('"')
                    bucket["title"] = str(title_text).strip()
                elif isinstance(parsed, dict):
                    bucket["title"] = (parsed.get("title") or parsed.get("name") or "").strip()
            elif images_id is not None and tid == images_id:
                bucket["images"] = parsed
            elif meta_id is not None and tid == meta_id:
                bucket["meta"] = parsed
        return by_key

    def _load_last_played(self, conn, release_keys):
        if not release_keys or not self._table_exists(conn, "LastPlayedDates"):
            return {}
        cols = {row[1].lower() for row in conn.execute("PRAGMA table_info(LastPlayedDates)")}
        rk_col = "releasekey" if "releasekey" in cols else None
        lp_col = None
        for candidate in ("lastplayeddate", "last_played", "lastplayed"):
            if candidate in cols:
                lp_col = candidate
                break
        if not rk_col or not lp_col:
            return {}
        placeholders = ",".join("?" * len(release_keys))
        sql = f"SELECT {rk_col}, {lp_col} FROM LastPlayedDates WHERE {rk_col} IN ({placeholders})"
        out = {}
        for rk, raw in conn.execute(sql, release_keys):
            if raw and str(raw).strip() and (not str(raw).startswith("0001-01-01")):
                text = str(raw)
                if "T" in text:
                    text = text.split("T")[0]
                out[str(rk)] = text
        return out

    def _load_parent_keys(self, conn, release_keys, type_ids):
        if not release_keys or not self._table_exists(conn, "GamePieces"):
            return set()
        parent_id = type_ids.get("parent")
        if parent_id is None:
            return set()
        placeholders = ",".join("?" * len(release_keys))
        sql = f"SELECT releaseKey, value FROM GamePieces WHERE releaseKey IN ({placeholders}) AND gamePieceTypeId = ?"
        out = set()
        for rk, value in conn.execute(sql, [*release_keys, parent_id]):
            parsed = _parse_json_value(value)
            if parsed is None:
                continue
            if isinstance(parsed, str) and (not parsed.strip()):
                continue
            if isinstance(parsed, dict) and (not parsed):
                continue
            out.add(str(rk))
        return out

    def _load_dlc_keys(self, conn, type_ids):
        dlcs_id = type_ids.get("dlcs")
        if dlcs_id is None or not self._table_exists(conn, "GamePieces"):
            return set()
        out = set()
        for (value,) in conn.execute("SELECT value FROM GamePieces WHERE gamePieceTypeId = ?", (dlcs_id,)):
            parsed = _parse_json_value(value)
            if not isinstance(parsed, dict):
                continue
            for item in parsed.get("dlcs") or []:
                if isinstance(item, str) and item.strip():
                    out.add(item.strip())
                elif isinstance(item, dict):
                    key = item.get("releaseKey") or item.get("id")
                    if key:
                        out.add(str(key))
        return out

    def _load_product_link_components(self, conn, release_keys, type_ids):
        links_id = type_ids.get("productlinks")
        if links_id is None or not release_keys or (not self._table_exists(conn, "GamePieces")):
            return {}
        placeholders = ",".join("?" * len(release_keys))
        sql = f"SELECT releaseKey, value FROM GamePieces WHERE releaseKey IN ({placeholders}) AND gamePieceTypeId = ?"
        out = {}
        owned = set(release_keys)
        for rk, value in conn.execute(sql, [*release_keys, links_id]):
            parsed = _parse_json_value(value)
            components = _extract_link_release_keys(parsed)
            components = {k for k in components if k in owned and k.startswith("gog_")}
            if len(components) >= 2:
                out[str(rk)] = components
        return out

    def get_library_records(self):
        conn = self._connect_ro()
        try:
            type_ids = self._load_type_ids(conn)
            release_keys = self._owned_release_keys(conn)
            dlc_keys = self._load_parent_keys(conn, release_keys, type_ids)
            dlc_keys |= self._load_dlc_keys(conn, type_ids)
            pack_components = self._load_product_link_components(conn, release_keys, type_ids)
            pieces = self._load_pieces_for_keys(conn, release_keys, type_ids)
            last_played = self._load_last_played(conn, release_keys)
            owned_keys = set(release_keys)
        finally:
            conn.close()
        records = []
        seen_ids = set()
        for rk in release_keys:
            if rk in dlc_keys:
                continue
            gog_id = _gog_id_from_release_key(rk)
            if gog_id is None or gog_id in seen_ids:
                continue
            seen_ids.add(gog_id)
            piece = pieces.get(rk, {})
            title = (piece.get("title") or "").strip() or f"GOG {gog_id}"
            meta = piece.get("meta")
            images = piece.get("images")
            cover = _pick_cover_url(images)
            records.append(
                {
                    "gog_id": gog_id,
                    "release_key": rk,
                    "name": title,
                    "raw_image": cover,
                    "header_image": cover,
                    "library_image": cover,
                    "release_date": _release_date_from_meta(meta),
                    "last_played": last_played.get(rk),
                    "genres": _genres_from_meta(meta),
                    "store_url": _meta_store_url(meta, gog_id),
                }
            )
        records = apply_gog_name_filters(records, pack_component_keys=pack_components, owned_release_keys=owned_keys)
        return sorted(records, key=lambda r: r["name"].lower())


def _extract_link_release_keys(parsed):
    keys = set()
    if isinstance(parsed, dict):
        for field in ("links", "products", "includedProducts", "includedInProducts", "productLinks"):
            raw = parsed.get(field)
            if isinstance(raw, list):
                for item in raw:
                    keys |= _extract_link_release_keys(item)
            elif isinstance(raw, dict):
                keys |= _extract_link_release_keys(raw)
        for key in ("releaseKey", "gameReleaseKey", "id"):
            val = parsed.get(key)
            if isinstance(val, str) and val.strip():
                keys.add(val.strip())
    elif isinstance(parsed, list):
        for item in parsed:
            keys |= _extract_link_release_keys(item)
    elif isinstance(parsed, str) and parsed.strip().startswith("gog_"):
        keys.add(parsed.strip())
    return keys
