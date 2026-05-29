#!/usr/bin/env python3
"""One-off fix store_url fields in existing games_*.json (no API calls)."""

import json
import re
from pathlib import Path
from urllib.parse import quote

_PUBLIC_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")
GENERIC_AMAZON = {"https://gaming.amazon.com/home", "https://gaming.amazon.com/home/"}


def fix_gog(g: dict) -> bool:
    url = (g.get("store_url") or "").strip()
    if url.startswith("http"):
        return False
    if url.startswith("/"):
        g["store_url"] = f"https://www.gog.com{url}"
        return True
    slug = g.get("slug") or g.get("gog_id")
    if slug:
        g["store_url"] = f"https://www.gog.com/en/game/{slug}"
        return True
    return False


def fix_epic(g: dict) -> bool:
    url = (g.get("store_url") or "").strip()
    if "/p/" not in url:
        return False
    slug = url.rsplit("/p/", 1)[-1].split("?")[0].split("/")[0]
    if _PUBLIC_SLUG.match(slug):
        return False
    name = g.get("name") or ""
    g["store_url"] = f"https://store.epicgames.com/en-US/browse?q={quote(name)}"
    return True


def fix_amazon(g: dict) -> bool:
    url = (g.get("store_url") or "").strip()
    if url not in GENERIC_AMAZON:
        return False
    asin = g.get("asin")
    title = g.get("name") or ""
    if asin:
        g["store_url"] = f"https://www.amazon.com/dp/{asin}"
    else:
        g["store_url"] = f"https://www.amazon.com/s?k={quote(title)}&i=videogames"
    return True


def patch_file(path: Path, fixer) -> int:
    if not path.exists():
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    n = 0
    for g in data.get("games", []):
        if fixer(g):
            n += 1
    if n:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return n


def main() -> int:
    root = Path(__file__).resolve().parent
    counts = {
        "gog": patch_file(root / "games_gog.json", fix_gog),
        "epic": patch_file(root / "games_epic.json", fix_epic),
        "amazon": patch_file(root / "games_amazon.json", fix_amazon),
    }
    for store, n in counts.items():
        print(f"{store}: updated {n} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
