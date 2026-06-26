#!/usr/bin/env python3
"""Fetch Epic Games Store library into games_epic.json for the dashboard."""

import argparse
import concurrent.futures
import hashlib
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv

from auth import mark_invalid, resolve_env
from clients.epic_client import LOGIN_URL, EpicAuthError, EpicClient, EpicCorrectiveActionError, default_epic_cache_dir
from clients.hltb_client import HltbClient
from fetchers._authoritative import EPIC
from fetchers._base import (
    add_allow_empty_arg,
    add_no_carry_arg,
    add_only_new_arg,
    apply_carry_forward,
    catalog_file,
    configure_stdout,
    merge_cached_row,
    refuse_drift_result,
    refuse_empty_result,
    row_key_by_id,
    write_catalog_text,
)
from fetchers._progress import EXIT_CODE_AUTH, HeartbeatTimer, RunStats, started
from shared.library_noise import is_entitlement_slug, should_auto_hide_by_title

GAMES_EPIC_JSON = Path("games_epic.json")
HLTB_DELAY_SEC = 1.0
CATALOG_WORKERS = 16

LIBRARY_IMAGE_TYPES = (
    "DieselGameBoxTall",
    "Thumbnail",
    "OfferImageTall",
    "VaultClosed",
    "DieselGameBox",
)
HEADER_IMAGE_TYPES = (
    "OfferImageWide",
    "DieselStoreFrontWide",
    "DieselGameBox",
    "Featured",
)


def _pick_image(key_images: list, types: tuple[str, ...]) -> str | None:
    by_type = {k.get("type"): k.get("url") for k in key_images if isinstance(k, dict)}
    for t in types:
        url = by_type.get(t)
        if url:
            return url
    return None


def _extract_genres(item: dict) -> list[str]:
    genres: list[str] = []
    for tag in item.get("tags") or []:
        if isinstance(tag, str):
            genres.append(tag)
        elif isinstance(tag, dict):
            name = tag.get("name") or tag.get("id")
            if name:
                genres.append(str(name))
    return list(dict.fromkeys(genres))


_PUBLIC_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _is_public_epic_slug(value: str | None) -> bool:
    """Real Epic store slugs are lowercase + digits + hyphens (e.g. ``fortnite``).

    Internal entitlement slugs like ``Fortnite_Studio`` or ``KingletAztec`` are
    PascalCase/snake_case and 404 on the public store.
    """
    return bool(value and _PUBLIC_SLUG.match(str(value).strip()))


def _epic_public_slug(item: dict, catalog_id: str) -> str | None:
    for key in ("productSlug", "urlSlug", "pageSlug"):
        slug = item.get(key)
        if _is_public_epic_slug(slug):
            return str(slug).strip()
    return None


def _epic_store_url(item: dict, catalog_id: str, name: str) -> str:
    slug = _epic_public_slug(item, catalog_id)
    if slug:
        return f"https://store.epicgames.com/en-US/p/{slug}"
    return f"https://store.epicgames.com/en-US/browse?q={quote(name)}"


def _epic_store_url_from_record(rec: dict, name: str) -> str:
    slug = rec.get("appName")
    if _is_public_epic_slug(slug):
        return f"https://store.epicgames.com/en-US/p/{slug}"
    return f"https://store.epicgames.com/en-US/browse?q={quote(name)}"


def _is_entitlement_slug(name: str | None) -> bool:
    """Internal entitlement slugs leak in as titles (e.g. ``Fortnite_StWContent``)."""
    return is_entitlement_slug(name)


# Epic catalog category paths that are never playable library games.
_NON_GAME_CATEGORY_FRAGMENTS = (
    "digitalextras",
    "engines",
    "software",
)


def _is_non_game_title(title: str | None) -> bool:
    s = str(title or "").strip()
    if not s:
        return False
    return should_auto_hide_by_title(s)


def _should_keep_game_row(row: dict) -> bool:
    """Final gate on output rows (catches cached survivors from merge_cached_row)."""
    return not _is_non_game_title(row.get("name"))


def _can_reuse_cached_epic_row(
    cached: dict,
    catalog_item: dict | None,
    *,
    skip_hltb: bool = False,
) -> bool:
    """Whether a prior on-disk row can skip catalog rebuild + enrichment.

    Stale rows survive when ``hltb_main_hours`` is ``0`` (not ``None``) and a
    library image exists — e.g. sandboxName ``Live`` rows that HLTB matched to
    ShellShock Live while the catalog title is a train-sim DLC route.

    The UI always runs Epic with ``--skip-hltb`` (see manifest.json); a blind
    cache append on that flag bypassed all catalog validation before this check.
    """
    if catalog_item is not None:
        if not _is_game_item(catalog_item):
            return False
        catalog_title = str(catalog_item.get("title") or "").strip()
        cached_name = str(cached.get("name") or "").strip()
        if catalog_title and cached_name and catalog_title.lower() != cached_name.lower():
            return False
    if not skip_hltb and cached.get("hltb_main_hours") is None:
        return False
    if not cached.get("library_image"):
        return False
    return True


def _epic_row_id(rec: dict) -> str:
    return f"{rec['namespace']}:{rec['catalogItemId']}"


def _entitlement_set_hash(apps: list[dict]) -> str:
    ids = sorted(_epic_row_id(rec) for rec in apps)
    return hashlib.sha256("\n".join(ids).encode()).hexdigest()[:16]


def _needs_catalog_fetch(rec: dict, existing: dict[str, dict], args: argparse.Namespace) -> bool:
    """Whether this entitlement needs a live catalog API lookup."""
    if args.refresh:
        return True
    row_id = _epic_row_id(rec)
    cached = existing.get(row_id)
    if cached is None:
        return True
    if not _should_keep_game_row(cached):
        return True
    may_reuse = args.skip_hltb or (
        cached.get("hltb_main_hours") is not None and cached.get("library_image")
    )
    if not may_reuse:
        return True
    return not _can_reuse_cached_epic_row(cached, None, skip_hltb=args.skip_hltb)


def _is_game_item(item: dict) -> bool:
    title = item.get("title")
    if _is_non_game_title(title):
        return False
    paths = [
        str(c.get("path", "")).lower()
        for c in (item.get("categories") or [])
        if isinstance(c, dict)
    ]
    if any(any(frag in p for frag in _NON_GAME_CATEGORY_FRAGMENTS) for p in paths):
        return False
    if any("addons" in p and "games" not in p for p in paths):
        return False
    if any("games" in p for p in paths):
        return True
    # keyImages alone is insufficient — Epic tags soundtracks/editors with cover art.
    return bool(title and item.get("keyImages"))


def _build_game_row(
    catalog_id: str,
    namespace: str,
    item: dict,
    hltb: dict | None,
) -> dict | None:
    if not _is_game_item(item):
        return None
    name = item.get("title") or catalog_id
    key_images = item.get("keyImages") or []
    header = _pick_image(key_images, HEADER_IMAGE_TYPES)
    library = _pick_image(key_images, LIBRARY_IMAGE_TYPES) or header
    store_url = _epic_store_url(item, catalog_id, name)

    release = None
    for info in item.get("releaseInfo") or []:
        if isinstance(info, dict) and info.get("date"):
            release = info["date"]
            break

    row = {
        "store": "epic",
        "id": f"{namespace}:{catalog_id}",
        "epic_namespace": namespace,
        "epic_catalog_id": catalog_id,
        "name": name,
        "playtime_minutes": 0,
        "last_played": None,
        "header_image": header,
        "library_image": library,
        "release_date": release,
        "genres": _extract_genres(item),
        "tags": [],
        "steam_review_percent": None,
        "steam_review_count": None,
        "steam_review_desc": None,
        "hltb_main_hours": None,
        "hltb_main_extra_hours": None,
        "hltb_completionist_hours": None,
        "hltb_match_confidence": None,
        "hltb_name": None,
        "store_url": store_url,
        "type": "game",
        "price": None,
        "price_initial": None,
        "discount_percent": None,
        "currency": None,
        "acquired_at": None,
    }
    if hltb:
        row.update(
            {
                "hltb_main_hours": hltb.get("hltb_main_hours"),
                "hltb_main_extra_hours": hltb.get("hltb_main_extra_hours"),
                "hltb_completionist_hours": hltb.get("hltb_completionist_hours"),
                "hltb_match_confidence": hltb.get("hltb_match_confidence"),
                "hltb_name": hltb.get("hltb_name"),
            }
        )
    return row


def _acquired_at_from_record(rec: dict | None) -> str | None:
    if not rec:
        return None
    val = rec.get("acquisitionDate")
    if isinstance(val, str) and val.strip():
        return val.strip()
    return None


def _build_game_row_from_record(
    rec: dict,
    catalog_item: dict | None,
    hltb: dict | None,
) -> dict | None:
    ns = rec.get("namespace")
    cid = rec.get("catalogItemId")
    if not ns or not cid:
        return None
    # When catalog metadata exists, trust the game-vs-addon filter in
    # _build_game_row. If it rejects the item (soundtrack/wallpaper/editor/
    # asset pack), skip it — do NOT fall through to the bare fallback below,
    # which would resurrect the very rows the filter deliberately dropped.
    if catalog_item is not None:
        row = _build_game_row(str(cid), str(ns), catalog_item, hltb)
        if row is not None:
            acquired = _acquired_at_from_record(rec)
            if acquired:
                row["acquired_at"] = acquired
        return row
    name = rec.get("sandboxName") or rec.get("appName") or str(cid)
    # No catalog hit: the only signal we have is the record name. Drop internal
    # entitlement slugs (e.g. Fortnite_StWContent) that aren't real titles.
    if _is_entitlement_slug(name):
        return None
    row = {
        "store": "epic",
        "id": f"{ns}:{cid}",
        "epic_namespace": ns,
        "epic_catalog_id": cid,
        "name": name,
        "playtime_minutes": 0,
        "last_played": None,
        "header_image": None,
        "library_image": None,
        # acquisitionDate is when the user added the game to their Epic library,
        # NOT the game's release date — leaving it here made old titles surface
        # as "New release". enrich_steam_tags backfills a real date when matched.
        "release_date": None,
        "genres": [],
        "tags": [],
        "steam_review_percent": None,
        "steam_review_count": None,
        "steam_review_desc": None,
        "hltb_main_hours": None,
        "hltb_main_extra_hours": None,
        "hltb_completionist_hours": None,
        "hltb_match_confidence": None,
        "hltb_name": None,
        "store_url": _epic_store_url_from_record(rec, name),
        "type": "game",
        "price": None,
        "price_initial": None,
        "discount_percent": None,
        "currency": None,
        "acquired_at": _acquired_at_from_record(rec),
    }
    if hltb:
        row.update(
            {
                "hltb_main_hours": hltb.get("hltb_main_hours"),
                "hltb_main_extra_hours": hltb.get("hltb_main_extra_hours"),
                "hltb_completionist_hours": hltb.get("hltb_completionist_hours"),
                "hltb_match_confidence": hltb.get("hltb_match_confidence"),
                "hltb_name": hltb.get("hltb_name"),
            }
        )
    return row


def load_existing() -> dict[str, dict]:
    if not catalog_file(GAMES_EPIC_JSON).exists():
        return {}
    data = json.loads(catalog_file(GAMES_EPIC_JSON).read_text(encoding="utf-8"))
    return {g["id"]: g for g in data.get("games", [])}


def print_auth_help() -> None:
    session_path = default_epic_cache_dir() / "session.json"
    print(
        f"""
Epic login is NOT a cookie from DevTools.

1. Sign in at https://www.epicgames.com in your browser.
2. Open this URL in the same browser (copy/paste the whole line):

{LOGIN_URL}

3. You should see a JSON page like:
   {{"authorizationCode":"abc123...","redirectUrl":"..."}}
4. Copy only the authorizationCode value into .env:
   EPIC_AUTH_CODE=abc123...
5. Run: python fetch_epic.py

The code expires in ~5 minutes. After the first successful run, a refresh
token is saved in {session_path} and you won't need the code again.
"""
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch Epic library into games_epic.json")
    parser.add_argument("--refresh", action="store_true", help="Re-fetch all catalog metadata")
    parser.add_argument("--skip-hltb", action="store_true", help="Skip HowLongToBeat lookups")
    add_only_new_arg(parser)
    parser.add_argument("--auth-help", action="store_true", help="Print Epic login instructions")
    add_allow_empty_arg(parser)
    add_no_carry_arg(parser)
    args = parser.parse_args()
    configure_stdout()
    t0 = started("fetch_epic")
    stats = RunStats()

    if args.auth_help:
        print_auth_help()
        return stats.finish("fetch_epic", t0, exit_code=0)

    load_dotenv()
    auth_code = resolve_env("EPIC_AUTH_CODE", provider="epic") or None

    try:
        client = EpicClient(auth_code=auth_code, cache_dir=default_epic_cache_dir())
        print("Logging in to Epic...")
        client.login()
        print(f"  account {client.account_id}")
    except EpicCorrectiveActionError as e:
        mark_invalid("epic", error=str(e))
        stats.error(str(e))
        print(f"Epic privacy-policy action required: {e}", flush=True)
        return stats.finish("fetch_epic", t0, exit_code=EXIT_CODE_AUTH)
    except EpicAuthError as e:
        mark_invalid("epic", error=str(e))
        stats.error(str(e))
        print_auth_help()
        return stats.finish("fetch_epic", t0, exit_code=EXIT_CODE_AUTH)

    print("Fetching library...")
    records = client.get_library_records()
    apps = [r for r in records if r.get("recordType") == "APPLICATION"]
    # Drop the Unreal Engine marketplace namespace ("ue"): these are engine asset
    # packs (e.g. the Infinity Blade content packs), not playable store games.
    ue_dropped = sum(1 for r in apps if str(r.get("namespace")) == "ue")
    apps = [r for r in apps if str(r.get("namespace")) != "ue"]
    print(
        f"  {len(records)} entitlements, {len(apps)} applications "
        f"(dropped {ue_dropped} UE marketplace assets)",
        flush=True,
    )

    # Epic tracks playtime per artifact (== entitlement appName), separate from
    # the library/catalog feed. Pull it once; non-fatal if the feed is empty or
    # unavailable so a playtime hiccup never blocks the library refresh.
    playtime_by_artifact: dict[str, int] = {}
    try:
        playtime_by_artifact = client.get_playtime()
    except EpicAuthError as e:
        stats.warn(f"playtime: {e}")
    if playtime_by_artifact:
        print(f"  playtime tracked for {len(playtime_by_artifact)} titles", flush=True)

    empty_exit = refuse_empty_result(
        apps,
        label="Epic library",
        allow_empty=args.allow_empty,
        output_path=GAMES_EPIC_JSON,
    )
    if empty_exit is not None:
        return stats.finish("fetch_epic", t0, exit_code=empty_exit)
    drift_exit = refuse_drift_result(
        apps,
        label="Epic library",
        allow_drift=args.allow_drift,
        output_path=GAMES_EPIC_JSON,
    )
    if drift_exit is not None:
        return stats.finish("fetch_epic", t0, exit_code=drift_exit)

    existing = load_existing()
    set_hash = _entitlement_set_hash(apps)
    prev_hash: str | None = None
    if catalog_file(GAMES_EPIC_JSON).exists():
        try:
            prev_hash = json.loads(
                catalog_file(GAMES_EPIC_JSON).read_text(encoding="utf-8")
            ).get("entitlement_set_hash")
        except json.JSONDecodeError:
            prev_hash = None
    if args.only_new and not args.refresh and prev_hash and set_hash == prev_hash:
        apps_needing_catalog: list[dict] = []
        catalog_skipped = len(apps)
        print(
            f"  catalog: entitlement set unchanged ({len(apps)} titles, no API calls)",
            flush=True,
        )
    else:
        apps_needing_catalog = apps if args.refresh else [
            rec for rec in apps if _needs_catalog_fetch(rec, existing, args)
        ]
        catalog_skipped = len(apps) - len(apps_needing_catalog)
    catalog: dict[tuple[str, str], dict] = {}

    if apps_needing_catalog:
        if catalog_skipped:
            print(
                f"Fetching catalog metadata for {len(apps_needing_catalog)} entitlements "
                f"({catalog_skipped} cached, skipping API) — {CATALOG_WORKERS} workers...",
                flush=True,
            )
        else:
            print(f"Fetching catalog metadata ({CATALOG_WORKERS} workers)...", flush=True)

        def fetch_one(rec: dict) -> tuple[tuple[str, str], dict | None]:
            ns, cid = str(rec["namespace"]), str(rec["catalogItemId"])
            return (ns, cid), client.get_catalog_item(ns, cid)

        catalog_hb = HeartbeatTimer(interval=25.0)
        with concurrent.futures.ThreadPoolExecutor(max_workers=CATALOG_WORKERS) as ex:
            futures = [ex.submit(fetch_one, rec) for rec in apps_needing_catalog]
            for i, fut in enumerate(concurrent.futures.as_completed(futures), 1):
                catalog_hb.tick_progress(
                    i, len(futures), "Epic catalog", f"{len(catalog)} hits"
                )
                try:
                    key, item = fut.result()
                    if item:
                        catalog[key] = item
                except Exception as e:
                    stats.warn(f"catalog: {e}")

        print(f"  catalog hits: {len(catalog)}/{len(apps_needing_catalog)}")
    elif catalog_skipped:
        print(f"  catalog: all {catalog_skipped} entitlements reused from cache (no API calls)", flush=True)

    # Sum playtime seconds per (namespace, title) so editions/DLC entitlements
    # that collapse into one library row (e.g. cross-edition Fortnite) report
    # their combined time — mirrors the PSN cross-gen playtime fix.
    playtime_sec_by_key: dict[tuple[str, str], int] = {}
    if playtime_by_artifact:
        for rec in apps:
            secs = playtime_by_artifact.get(str(rec.get("appName")))
            if not secs:
                continue
            ns = str(rec.get("namespace"))
            item = catalog.get((ns, str(rec.get("catalogItemId"))))
            nm = (
                (item or {}).get("title")
                or rec.get("sandboxName")
                or rec.get("appName")
                or str(rec.get("catalogItemId"))
            ).strip().lower()
            playtime_sec_by_key[(ns, nm)] = playtime_sec_by_key.get((ns, nm), 0) + int(secs)

    hltb_client = HltbClient()
    games_out: list[dict] = []
    skipped = 0

    apps_sorted = sorted(
        apps,
        key=lambda r: (r.get("sandboxName") or r.get("appName") or "").lower(),
    )
    for i, rec in enumerate(apps_sorted, 1):
        ns, cid = str(rec["namespace"]), str(rec["catalogItemId"])
        row_id = _epic_row_id(rec)
        item = catalog.get((ns, cid))
        name = (item or {}).get("title") or rec.get("sandboxName") or rec.get("appName") or cid

        if args.only_new and row_id in existing and not args.refresh:
            games_out.append(existing[row_id])
            continue

        if not args.refresh and row_id in existing:
            cached_early = existing[row_id]
            may_reuse = args.skip_hltb or (
                cached_early.get("hltb_main_hours") is not None
                and cached_early.get("library_image")
            )
            if may_reuse and _can_reuse_cached_epic_row(
                cached_early, item, skip_hltb=args.skip_hltb
            ):
                games_out.append(cached_early)
                continue

        print(f"[{i}/{len(apps_sorted)}] {name}")

        hltb = None
        hltb_updated = False
        cached_row = existing.get(row_id)
        if not args.skip_hltb and (
            args.refresh or cached_row is None or cached_row.get("hltb_main_hours") is None
        ):
            try:
                time.sleep(HLTB_DELAY_SEC)
                hltb = hltb_client.lookup(name)
                hltb_updated = bool(hltb)
            except Exception as e:
                print(f"  HLTB warning: {e}")
        elif cached_row:
            hltb = {
                "hltb_main_hours": cached_row.get("hltb_main_hours"),
                "hltb_main_extra_hours": cached_row.get("hltb_main_extra_hours"),
                "hltb_completionist_hours": cached_row.get("hltb_completionist_hours"),
                "hltb_match_confidence": cached_row.get("hltb_match_confidence"),
                "hltb_name": cached_row.get("hltb_name"),
            }

        row = _build_game_row_from_record(rec, item, hltb)
        if row is None:
            skipped += 1
            continue
        merged = merge_cached_row(row, cached_row, authoritative=EPIC, hltb_updated=hltb_updated)
        if not _should_keep_game_row(merged):
            skipped += 1
            continue
        games_out.append(merged)

    # Drop any non-game extras that survived via cached rows (name is not in the
    # Epic authoritative merge set, so old soundtracks/editors can linger).
    filtered: list[dict] = []
    filtered_non_game = 0
    for g in games_out:
        if _should_keep_game_row(g):
            filtered.append(g)
        else:
            filtered_non_game += 1
    games_out = filtered

    # Collapse duplicate entitlements: Epic hands out many catalogItemIds under
    # one namespace for the same title (base game + editions/DLC tokens that all
    # report the identical name), e.g. "Fallout: New Vegas" x7. Keep the first
    # row per (namespace, name) — distinct names in a namespace (real DLC like
    # "ARK Ragnarok") are preserved.
    deduped: list[dict] = []
    seen: set[tuple[str, str]] = set()
    collapsed = 0
    for g in games_out:
        key = (str(g.get("epic_namespace")), (g.get("name") or "").strip().lower())
        if key in seen:
            collapsed += 1
            continue
        seen.add(key)
        deduped.append(g)
    games_out = deduped

    drift_exit = refuse_drift_result(
        games_out,
        label="Epic library rows",
        allow_drift=args.allow_drift,
        output_path=GAMES_EPIC_JSON,
    )
    if drift_exit is not None:
        return stats.finish("fetch_epic", t0, exit_code=drift_exit)

    games_out = apply_carry_forward(
        games_out,
        existing,
        key_fn=row_key_by_id,
        no_carry=args.no_carry,
    )

    if playtime_sec_by_key:
        playtime_applied = 0
        for g in games_out:
            key = (str(g.get("epic_namespace")), (g.get("name") or "").strip().lower())
            secs = playtime_sec_by_key.get(key)
            if secs:
                g["playtime_minutes"] = int(round(secs / 60))
                playtime_applied += 1
        print(f"  applied playtime to {playtime_applied} games", flush=True)

    payload = {
        "fetched_at": datetime.now(UTC).isoformat(),
        "store": "epic",
        "game_count": len(games_out),
        "entitlement_set_hash": set_hash,
        "games": sorted(games_out, key=lambda g: g["name"].lower()),
    }
    write_catalog_text(GAMES_EPIC_JSON, json.dumps(payload, indent=2, ensure_ascii=False))
    print(
        f"\nWrote {len(games_out)} games to {GAMES_EPIC_JSON} "
        f"(skipped {skipped}, filtered {filtered_non_game} non-game extras, "
        f"collapsed {collapsed} duplicate entitlements).",
        flush=True,
    )
    print("Reload the dashboard (or click Reload library) to refresh Picks.", flush=True)
    stats.ok = len(games_out)
    return stats.finish("fetch_epic", t0, exit_code=0, extra=f"{len(games_out)} games")


if __name__ == "__main__":
    raise SystemExit(main())
