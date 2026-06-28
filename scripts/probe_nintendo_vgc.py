import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from auth.secrets import profile_dir
from clients.nintendo_vgc import NintendoVgcAuthError, NintendoVgcCaptureError, NintendoVgcClient
from fetchers._base import catalog_file
from shared.profile_paths import profile_cache_dir

GAMES_NINTENDO_JSON = Path("games_nintendo.json")
RAW_DUMP = profile_cache_dir() / "nintendo" / "vgc_probe.json"
SUMMARY_DUMP = profile_cache_dir() / "nintendo" / "vgc_probe_summary.json"


def _norm_title(name):
    return " ".join((name or "").lower().split())


def _load_catalog_games():
    path = catalog_file(GAMES_NINTENDO_JSON)
    if not path.exists():
        return []
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    games = doc.get("games")
    return [g for g in games if isinstance(g, dict)] if isinstance(games, list) else []


def diff_vgc_vs_catalog(vgc_rows, catalog_games):
    vgc_by_title = {_norm_title(r.get("name") or ""): r for r in vgc_rows if r.get("name")}
    cat_by_title = {_norm_title(g.get("name") or ""): g for g in catalog_games if g.get("name")}
    only_vgc = sorted((title for title in vgc_by_title if title and title not in cat_by_title))
    only_catalog = sorted((title for title in cat_by_title if title and title not in vgc_by_title))
    shared = sorted((title for title in vgc_by_title if title in cat_by_title))
    legacy_only = [
        g.get("name") or ""
        for g in catalog_games
        if g.get("nintendo_legacy") and _norm_title(g.get("name") or "") not in vgc_by_title
    ]
    legacy_only.sort(key=_norm_title)
    return {
        "vgc_count": len(vgc_rows),
        "catalog_count": len(catalog_games),
        "catalog_fresh_count": sum((1 for g in catalog_games if not g.get("nintendo_legacy") and (not g.get("stale")))),
        "catalog_legacy_count": sum((1 for g in catalog_games if g.get("nintendo_legacy"))),
        "shared_title_count": len(shared),
        "only_vgc_titles": only_vgc,
        "only_catalog_titles": only_catalog,
        "legacy_not_in_vgc_titles": legacy_only,
        "sample_only_vgc": [
            {
                "name": vgc_by_title[t]["name"],
                "application_id": vgc_by_title[t].get("application_id"),
                "platform": vgc_by_title[t].get("platform"),
            }
            for t in only_vgc[:15]
        ],
        "sample_only_catalog": [
            {
                "name": cat_by_title[t].get("name"),
                "id": cat_by_title[t].get("id"),
                "nintendo_legacy": bool(cat_by_title[t].get("nintendo_legacy")),
            }
            for t in only_catalog[:15]
        ],
    }


def _print_summary(summary):
    print(f"VGC cards:           {summary['vgc_count']}")
    print(f"Catalog games:       {summary['catalog_count']}")
    print(f"  fresh (non-legacy): {summary['catalog_fresh_count']}")
    print(f"  nintendo_legacy:    {summary['catalog_legacy_count']}")
    print(f"Shared by title:     {summary['shared_title_count']}")
    print(f"Only in VGC:         {len(summary['only_vgc_titles'])}")
    print(f"Only in catalog:     {len(summary['only_catalog_titles'])}")
    print(f"Legacy not in VGC:   {len(summary['legacy_not_in_vgc_titles'])}")
    if summary["sample_only_vgc"]:
        print("\nSample only-in-VGC (up to 15):")
        for row in summary["sample_only_vgc"]:
            print(f"  - {row['name']}  (app {row.get('application_id')}, {row.get('platform') or 'platform?'})")
    if summary["sample_only_catalog"]:
        print("\nSample only-in-catalog (up to 15):")
        for row in summary["sample_only_catalog"]:
            tag = " [legacy]" if row.get("nintendo_legacy") else ""
            print(f"  - {row['name']}  (id {row.get('id')}){tag}")
    if summary["legacy_not_in_vgc_titles"]:
        print("\nLegacy catalog rows with no VGC title match (first 10):")
        for name in summary["legacy_not_in_vgc_titles"][:10]:
            print(f"  - {name}")


def main():
    parser = argparse.ArgumentParser(description="Probe Nintendo VGC vs games_nintendo.json")
    parser.add_argument("--headed", action="store_true", help="Show browser window")
    parser.add_argument("--dump-raw", action="store_true", help=f"Write raw VGC rows to {RAW_DUMP}")
    args = parser.parse_args()
    prof = profile_dir("nintendo")
    if not prof.exists() or not any(prof.iterdir()):
        print(
            "Nintendo is not connected (no saved browser profile). Open Connections → Nintendo → Connect, then re-run.",
            file=sys.stderr,
        )
        return 1
    try:
        rows = NintendoVgcClient(profile_path=prof, headless=not args.headed).fetch_all_cards()
    except NintendoVgcAuthError as exc:
        print(f"AUTH: {exc}", file=sys.stderr)
        return 4
    except NintendoVgcCaptureError as exc:
        print(f"CAPTURE: {exc}", file=sys.stderr)
        return 1
    catalog = _load_catalog_games()
    summary = diff_vgc_vs_catalog(rows, catalog)
    summary["catalog_path"] = str(catalog_file(GAMES_NINTENDO_JSON))
    RAW_DUMP.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_DUMP.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.dump_raw:
        RAW_DUMP.write_text(json.dumps({"cards": rows}, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Wrote raw VGC dump to {RAW_DUMP}.")
    print(f"Wrote summary to {SUMMARY_DUMP}.\n")
    _print_summary(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
