"""Read Amazon Games library from the local launcher SQLite databases (Windows).

The launcher stores owned titles in ``Entitlements.sqlite`` as DPAPI-encrypted
JSON blobs. This module decrypts them with the current user's Windows login
(same machine / same account only).

Typical paths (``%LOCALAPPDATA%``):

- ``Amazon Games/Data/Games/Sql/Entitlements.sqlite`` — owned titles (required)
- ``Amazon Games/Data/Games/Sql/ProductDetails.sqlite`` — cached artwork/metadata
- ``Amazon Games/Data/Games/Sql/GameUserInteractionsInfo.sqlite`` — last played
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from pathlib import Path

if sys.platform != "win32":
    raise ImportError("amazon_client requires Windows (DPAPI decryption)")

import ctypes
from ctypes import wintypes

LOCALAPPDATA = Path(os.environ.get("LOCALAPPDATA", ""))
DEFAULT_SQL_DIR = LOCALAPPDATA / "Amazon Games" / "Data" / "Games" / "Sql"

ENTITLEMENTS_DB = "Entitlements.sqlite"
PRODUCT_DETAILS_DB = "ProductDetails.sqlite"
INTERACTIONS_DB = "GameUserInteractionsInfo.sqlite"


class AmazonGamesError(Exception):
    """Amazon Games data could not be read."""


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _bytes_to_blob(data: bytes) -> DATA_BLOB:
    buf = ctypes.create_string_buffer(data, len(data))
    return DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))


def dpapi_decrypt(data: bytes) -> bytes:
    """Decrypt a DPAPI blob for the current Windows user."""
    blob_in = _bytes_to_blob(data)
    blob_out = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(blob_out),
    ):
        raise AmazonGamesError(f"DPAPI decrypt failed (winerror {ctypes.GetLastError()})")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def _normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", (title or "").strip().lower())


def _pick_image_url(*urls: str | None) -> str | None:
    for url in urls:
        if not url:
            continue
        if url.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            return url
    for url in urls:
        if url and url.startswith("http"):
            return url
    return None


class AmazonGamesClient:
    def __init__(self, sql_dir: Path | str | None = None):
        self.sql_dir = Path(sql_dir) if sql_dir else DEFAULT_SQL_DIR
        self.entitlements_path = self.sql_dir / ENTITLEMENTS_DB
        if not self.entitlements_path.is_file():
            raise AmazonGamesError(
                f"Amazon Games database not found:\n  {self.entitlements_path}\n"
                "Install the Amazon Games app, sign in, and open your library once."
            )

    def _connect_ro(self, filename: str) -> sqlite3.Connection:
        path = self.sql_dir / filename
        if not path.is_file():
            raise FileNotFoundError(path)
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True)

    def _load_product_details_by_title(self) -> dict[str, dict]:
        path = self.sql_dir / PRODUCT_DETAILS_DB
        if not path.is_file():
            return {}
        out: dict[str, dict] = {}
        conn = self._connect_ro(PRODUCT_DETAILS_DB)
        try:
            for _key, raw in conn.execute("SELECT key, value FROM game_product_info"):
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                title = data.get("ProductTitle") or ""
                norm = _normalize_title(title)
                if norm:
                    out[norm] = data
        finally:
            conn.close()
        return out

    def _load_last_played_by_adg_id(self) -> dict[str, str]:
        """Map ``amzn1.adg.product.<uuid>`` → ISO-ish last played string."""
        path = self.sql_dir / INTERACTIONS_DB
        if not path.is_file():
            return {}
        out: dict[str, str] = {}
        conn = self._connect_ro(INTERACTIONS_DB)
        try:
            for adg_id, _seen, last_played in conn.execute(
                "SELECT Id, GameSeenInLibrary, LastPlayed FROM DbSet"
            ):
                if not last_played or str(last_played).startswith("0001-01-01"):
                    continue
                out[str(adg_id)] = str(last_played)
        finally:
            conn.close()
        return out

    def get_entitlements(self) -> list[dict]:
        """Decrypt and return raw entitlement JSON objects."""
        conn = self._connect_ro(ENTITLEMENTS_DB)
        rows: list[dict] = []
        try:
            for entitlement_id, blob in conn.execute(
                "SELECT key, value FROM game_entitlements"
            ):
                if not isinstance(blob, (bytes, memoryview)):
                    continue
                raw = bytes(blob)
                try:
                    data = json.loads(dpapi_decrypt(raw).decode("utf-8"))
                except (AmazonGamesError, json.JSONDecodeError, UnicodeDecodeError) as e:
                    raise AmazonGamesError(
                        f"Failed to decrypt entitlement {entitlement_id}: {e}"
                    ) from e
                data["_entitlement_id"] = entitlement_id
                rows.append(data)
        finally:
            conn.close()
        return rows

    def get_library_records(self) -> list[dict]:
        """Return normalized library rows ready for ``fetch_amazon.py``."""
        details_by_title = self._load_product_details_by_title()
        last_played_by_adg = self._load_last_played_by_adg_id()
        records: list[dict] = []
        seen_product_ids: set[str] = set()

        for ent in self.get_entitlements():
            title = (ent.get("ProductTitle") or "").strip()
            if not title:
                continue

            product_id = ent.get("ProductIdStr") or (ent.get("ProductId") or {}).get("Id")
            if not product_id:
                continue
            product_id = str(product_id)
            if product_id in seen_product_ids:
                continue
            seen_product_ids.add(product_id)

            cached = details_by_title.get(_normalize_title(title), {})
            adg_id = cached.get("Id") or cached.get("ProductId", {}).get("Id")
            if isinstance(adg_id, dict):
                adg_id = adg_id.get("Id")
            last_played = last_played_by_adg.get(str(adg_id)) if adg_id else None

            icon = _pick_image_url(
                cached.get("ProductIconUrl"),
                cached.get("Background"),
                cached.get("Background2"),
                ent.get("ProductIconUrl"),
            )
            library_img = _pick_image_url(
                cached.get("Background"),
                cached.get("Background2"),
                cached.get("ProductIconUrl"),
                icon,
            )

            asin = ent.get("ProductAsin") or cached.get("ProductAsin")
            if asin:
                store_url = f"https://www.amazon.com/dp/{asin}"
            else:
                from urllib.parse import quote

                store_url = (
                    f"https://www.amazon.com/s?k={quote(title)}&i=videogames"
                )

            genres = list(
                dict.fromkeys(
                    (ent.get("Genres") or [])
                    + (cached.get("Genres") or [])
                )
            )

            release = cached.get("ReleaseDate") or ent.get("ReleaseDate")
            if isinstance(release, str) and "T" in release:
                release = release.split("T")[0]

            records.append(
                {
                    "amazon_product_id": product_id,
                    "amazon_entitlement_id": ent.get("Id") or ent.get("_entitlement_id"),
                    "amazon_adg_id": adg_id,
                    "name": title,
                    "asin": asin,
                    "product_sku": ent.get("ProductSku"),
                    "product_line": ent.get("ProductLine"),
                    "header_image": icon,
                    "library_image": library_img,
                    "genres": genres,
                    "release_date": release,
                    "last_played": last_played,
                    "store_url": store_url,
                    "publisher": cached.get("ProductPublisher") or ent.get("ProductPublisher"),
                }
            )

        return sorted(records, key=lambda r: r["name"].lower())
