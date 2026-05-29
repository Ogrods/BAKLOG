"""For each Steam row whose library_image 404s, try a fallback chain.

Order:
  1. shared.akamai library_600x900_2x.jpg / library_600x900.jpg
  2. cloudflare CDN variants
  3. capsule_616x353 / capsule_231x87
  4. header.jpg (always exists for live apps)
  5. SteamGridDB (only if STEAMGRIDDB_KEY in .env)

Writes the first 200 OK URL into both library_image and header_image where
appropriate, and tags the row with image_source so we can audit.
"""

import concurrent.futures
import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
load_dotenv()

HEADERS = {"User-Agent": "Mozilla/5.0 backlog/1.0"}
TIMEOUT = 8


def head_or_get(url: str) -> int:
    try:
        r = requests.get(url, headers={**HEADERS, "Range": "bytes=0-127"}, timeout=TIMEOUT, stream=True)
        code = r.status_code
        r.close()
        return code
    except Exception:
        return 0


def steam_variants(appid: int) -> list[tuple[str, str]]:
    """Returns list of (role, url). role is 'library' (600x900) or 'header'."""
    cdns = [
        "https://shared.akamai.steamstatic.com",
        "https://cdn.cloudflare.steamstatic.com",
        "https://cdn.akamai.steamstatic.com",
    ]
    out: list[tuple[str, str]] = []
    for cdn in cdns:
        out += [
            ("library", f"{cdn}/steam/apps/{appid}/library_600x900_2x.jpg"),
            ("library", f"{cdn}/steam/apps/{appid}/library_600x900.jpg"),
        ]
    for cdn in cdns:
        out += [
            ("header", f"{cdn}/steam/apps/{appid}/library_hero.jpg"),
            ("header", f"{cdn}/steam/apps/{appid}/capsule_616x353.jpg"),
            ("header", f"{cdn}/steam/apps/{appid}/header.jpg"),
            ("header", f"{cdn}/steam/apps/{appid}/capsule_231x87.jpg"),
        ]
    return out


def steamgriddb_lookup(appid: int, name: str, api_key: str) -> tuple[str | None, str | None]:
    """Returns (library_600x900_url, header_url) or (None, None)."""
    h = {"Authorization": f"Bearer {api_key}", **HEADERS}
    try:
        r = requests.get(
            f"https://www.steamgriddb.com/api/v2/games/steam/{appid}",
            headers=h, timeout=TIMEOUT,
        )
        if r.status_code != 200:
            search = requests.get(
                f"https://www.steamgriddb.com/api/v2/search/autocomplete/{requests.utils.quote(name)}",
                headers=h, timeout=TIMEOUT,
            ).json()
            data = (search.get("data") or [None])[0]
            if not data:
                return None, None
            sgdb_id = data["id"]
        else:
            sgdb_id = r.json()["data"]["id"]
        grids = requests.get(
            f"https://www.steamgriddb.com/api/v2/grids/game/{sgdb_id}",
            headers=h, params={"dimensions": "600x900", "limit": 1}, timeout=TIMEOUT,
        ).json()
        lib_url = (grids.get("data") or [{}])[0].get("url")
        heroes = requests.get(
            f"https://www.steamgriddb.com/api/v2/heroes/game/{sgdb_id}",
            headers=h, params={"limit": 1}, timeout=TIMEOUT,
        ).json()
        hero_url = (heroes.get("data") or [{}])[0].get("url")
        return lib_url, hero_url
    except Exception as e:
        print(f"  SteamGridDB error: {e}")
        return None, None


def find_replacement(appid: int, name: str, api_key: str | None) -> dict:
    chosen = {"library_image": None, "header_image": None, "image_source": None}
    variants = steam_variants(appid)
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
        results = list(ex.map(lambda u: (u[0], u[1], head_or_get(u[1])), variants))
    for role, url, code in results:
        if code >= 400 or code == 0:
            continue
        if role == "library" and not chosen["library_image"]:
            chosen["library_image"] = url
            chosen["image_source"] = "steam-cdn"
        elif role == "header" and not chosen["header_image"]:
            chosen["header_image"] = url
            if not chosen["image_source"]:
                chosen["image_source"] = "steam-cdn"
    if api_key and (not chosen["library_image"] or not chosen["header_image"]):
        lib, hero = steamgriddb_lookup(appid, name, api_key)
        if lib and not chosen["library_image"]:
            chosen["library_image"] = lib
            chosen["image_source"] = "steamgriddb"
        if hero and not chosen["header_image"]:
            chosen["header_image"] = hero
            chosen["image_source"] = chosen["image_source"] or "steamgriddb"
    return chosen


def main():
    api_key = os.getenv("STEAMGRIDDB_KEY", "").strip() or None
    broken = json.loads(Path("broken_images.json").read_text(encoding="utf-8"))
    targets = [b for b in broken if b["store"] == "steam"]
    print(f"Enriching {len(targets)} broken Steam images (SteamGridDB: {'yes' if api_key else 'no'})...")

    steam_path = Path("games_steam.json")
    data = json.loads(steam_path.read_text(encoding="utf-8"))
    by_id = {g["id"]: g for g in data["games"]}

    fixed_full = 0
    still_missing: list[dict] = []
    for i, t in enumerate(targets, 1):
        row = by_id.get(t["id"])
        if not row:
            continue
        print(f"[{i}/{len(targets)}] {t['name']} ({t['id']})")
        repl = find_replacement(t["id"], t["name"], api_key)
        if repl["header_image"] and not repl["library_image"]:
            repl["library_image"] = repl["header_image"]
        if repl["library_image"]:
            row["library_image"] = repl["library_image"]
        if repl["header_image"]:
            row["header_image"] = repl["header_image"]
        if repl["image_source"]:
            row["image_source"] = repl["image_source"]
        if repl["library_image"]:
            fixed_full += 1
            print(f"  fixed via {repl['image_source']}")
        else:
            print("  no replacement found")
            still_missing.append(t)

    steam_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print()
    print(f"Fixed: {fixed_full}")
    print(f"Still missing: {len(still_missing)}")
    if still_missing:
        Path("still_missing_images.json").write_text(
            json.dumps(still_missing, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        for s in still_missing:
            print(f"  - {s['id']:>10}  {s['name']}")


if __name__ == "__main__":
    main()
