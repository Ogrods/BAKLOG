#!/usr/bin/env python3
"""One-shot migrator: sponsors.json v1 items[] -> v2 ads{} + locations{}."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Sync pair: keep aligned with js/sponsored-deals.js AD_LOCATIONS keys.
PLACEMENT_TO_LOCATIONS: dict[str, list[str]] = {
    "spotlight": ["dash-spotlight"],
    "dash-feature-banner": ["dash-feature-banner"],
    "coop-online": ["dash-coop-online"],
    "coop-couch": ["dash-coop-couch"],
    "dash-picks": ["dash-pick"],
    "picks": ["lib-pick", "wish-pick", "deals-pick", "itch-pick"],
    "table": ["lib-row", "wish-row", "deals-row", "itch-row"],
    "claimable": ["claim-cards"],
    "deal-rail": ["wish-deal-hero"],
    "dash-deal-rail": ["dash-house"],
}

# Sync pair: keep aligned with js/sponsored-deals.js HOUSE_DEFAULTS +
# curated/sponsors.json. dismissible: closeable (session-scoped) house promos;
# the Pro promo + house-spotlight-pro-* slides are permanent (Pro-only removal).
HOUSE_DEFAULTS = {
    "house-support-baklog": {
        "kind": "house",
        "title": "Level up to BAKLOG Pro",
        "tagline": "Queue every stale store, sync across machines, and drop sponsored cards - $5/mo.",
        "cta": "Get Pro - $5/mo",
        "url": "https://buy.polar.sh/polar_cl_1BV0qvxl87f2YEGmZo36HvXdmTf4GHthbIjh92P2yNw",
        "cover": "",
        "dismissible": True,
        "enabled": True,
    },
    "house-pro-promo": {
        "kind": "house",
        "title": "Move faster. Cut the noise.",
        "tagline": (
            "Queue every stale store, sync across machines, and drop sponsored deal cards. "
            "Nothing you use today moves behind paywall."
        ),
        "cta": "Get Pro - $5/mo",
        "url": "https://buy.polar.sh/polar_cl_1BV0qvxl87f2YEGmZo36HvXdmTf4GHthbIjh92P2yNw",
        "cover": "",
        "enabled": True,
    },
    "house-lib-backlog": {
        "kind": "house",
        "title": "You own 600 games. You've played 40.",
        "tagline": "One honest backlog across every store. Private, Steam-ready.",
        "cta": "Get Pro - $5/mo",
        "url": "https://buy.polar.sh/polar_cl_1BV0qvxl87f2YEGmZo36HvXdmTf4GHthbIjh92P2yNw",
        "cover": "",
        "dismissible": True,
        "enabled": True,
    },
    "house-itch-privacy": {
        "kind": "house",
        "title": "Level up to BAKLOG Pro",
        "tagline": "Queue every stale store, sync across machines, and drop sponsored cards - $5/mo.",
        "cta": "Get Pro - $5/mo",
        "url": "https://buy.polar.sh/polar_cl_1BV0qvxl87f2YEGmZo36HvXdmTf4GHthbIjh92P2yNw",
        "cover": "",
        "dismissible": True,
        "enabled": True,
    },
    "house-spotlight-pro-logo": {
        "kind": "house",
        "title": "BAKLOG Pro",
        "slogan": "One honest backlog across every store.",
        "tagline": "Leveled up with bulk refresh, cloud sync, and no ads - $5/mo.",
        "cta": "Get Pro",
        "url": "https://buy.polar.sh/polar_cl_1BV0qvxl87f2YEGmZo36HvXdmTf4GHthbIjh92P2yNw",
        "cover": "",
        "art_mode": "logo",
        "scheme": "ember",
        "enabled": True,
    },
    "house-spotlight-pro-sync": {
        "kind": "house",
        "title": "Sync every machine",
        "slogan": (
            "Keep your library and personal data aligned across machines "
            "- no manual exports."
        ),
        "tagline": "Cloud sync for library JSON and personal prefs.",
        "cta": "Get Pro - $5/mo",
        "url": "https://buy.polar.sh/polar_cl_1BV0qvxl87f2YEGmZo36HvXdmTf4GHthbIjh92P2yNw",
        "cover": "",
        "art_mode": "logo",
        "scheme": "sapphire",
        "enabled": True,
    },
    "house-spotlight-pro-noads": {
        "kind": "house",
        "title": "Fewer distractions",
        "slogan": "Paid tier drops sponsored deal slots so your deal radar stays yours.",
        "tagline": "$5/mo - nothing you use today moves behind paywall.",
        "cta": "Get Pro - $5/mo",
        "url": "https://buy.polar.sh/polar_cl_1BV0qvxl87f2YEGmZo36HvXdmTf4GHthbIjh92P2yNw",
        "cover": "",
        "art_mode": "logo",
        "scheme": "emerald",
        "enabled": True,
    },
    "house-spotlight-library": {
        "kind": "house",
        "title": "It's just your library",
        "slogan": "It's not a godsend, it's just your library.",
        "tagline": (
            "Every game you already own, deduped across every store "
            "into one honest backlog. Local-first."
        ),
        "cta": "Get Pro - $5/mo",
        "url": "https://buy.polar.sh/polar_cl_1BV0qvxl87f2YEGmZo36HvXdmTf4GHthbIjh92P2yNw",
        "cover": "",
        "art_mode": "logo",
        "scheme": "sapphire",
        "enabled": True,
    },
}


def parse_placements(raw) -> list[str]:
    if raw is None or raw == "":
        return ["deal-rail"]
    if isinstance(raw, list):
        return [str(p).strip().lower() for p in raw if str(p).strip()]
    return [p.strip().lower() for p in str(raw).split(",") if p.strip()]


def migrate_v1(doc: dict) -> dict:
    items = doc.get("items") if isinstance(doc.get("items"), list) else []
    ads: dict[str, dict] = {}
    locations: dict[str, list[str]] = {k: [] for k in [
        "dash-spotlight", "dash-feature-banner", "dash-coop-online", "dash-coop-couch",
        "dash-versus-rated", "dash-versus-fast", "dash-pick", "dash-house",
        "lib-pick", "lib-row", "lib-house",
        "wish-pick", "wish-row", "wish-deal-hero", "wish-deal-portrait", "wish-house",
        "deals-pick", "deals-row",
        "itch-pick", "itch-row", "itch-house",
        "claim-cards",
    ]}

    versus_items: list[tuple[int, str]] = []

    for item in items:
        if not isinstance(item, dict):
            continue
        ad_id = str(item.get("id") or "").strip()
        if not ad_id:
            continue
        creative = {k: v for k, v in item.items() if k not in ("id", "placements", "priority")}
        ads[ad_id] = creative

        for placement in parse_placements(item.get("placements")):
            if placement == "dash-versus":
                versus_items.append((int(item.get("priority") or 99), ad_id))
                continue
            for loc in PLACEMENT_TO_LOCATIONS.get(placement, []):
                if ad_id not in locations[loc]:
                    locations[loc].append(ad_id)

    versus_items.sort(key=lambda x: x[0])
    for _, ad_id in versus_items[:1]:
        if ad_id not in locations["dash-versus-rated"]:
            locations["dash-versus-rated"].append(ad_id)
    for _, ad_id in versus_items[1:2]:
        if ad_id not in locations["dash-versus-fast"]:
            locations["dash-versus-fast"].append(ad_id)

    for hid, creative in HOUSE_DEFAULTS.items():
        ads.setdefault(hid, creative)

    house_locs = {
        "dash-house": "house-pro-promo",
        "wish-house": "house-support-baklog",
        "lib-house": "house-lib-backlog",
        "itch-house": "house-itch-privacy",
    }
    for loc, hid in house_locs.items():
        if not locations[loc] and hid in ads:
            locations[loc] = [hid]

    return {
        "version": 2,
        "generated_at": doc.get("generated_at"),
        "ads": ads,
        "locations": {k: v for k, v in locations.items() if v},
    }


def main() -> int:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "curated" / "sponsors.json"
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else src
    doc = json.loads(src.read_text(encoding="utf-8"))
    if doc.get("version") == 2:
        print("already v2", src)
        return 0
    out = migrate_v1(doc)
    dst.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote v2 ({len(out['ads'])} ads, {sum(len(v) for v in out['locations'].values())} assignments) -> {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
