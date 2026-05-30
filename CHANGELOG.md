# Changelog

All notable changes to this project are documented here.

## [Unreleased]

### Added

- Epic Games library fetcher (`fetch_epic.py`, `epic_client.py`)
- Amazon Prime Gaming fetcher (`fetch_amazon.py`, `amazon_client.py`) via local SQLite
- Xbox / Game Pass / Microsoft Store fetcher (`fetch_xbox.py`, `xbox_client.py`) via OpenXBL
- Battle.net fetcher (`fetch_battlenet.py`, `battlenet_client.py`) via unofficial cookie scrape
- Ubisoft Connect fetcher (`fetch_ubisoft.py`, `ubisoft_client.py`) via unofficial API headers
- Nintendo Switch fetcher (`fetch_nintendo.py`, `nintendo_client.py`) via eShop transactions (~2yr history; older/cartridge = manual Add Game)
- itch.io quarantine tab: `itchGames` array separate from `allGames`; Top Rated picks only; summary chip shows game count vs total keys
- itch.io non-game filter pill ("Hide tools, soundtracks, etc.") default-on; fetcher imports all owned keys
- Live service status in row dropdown, bulk toolbar, sidebar filter, and keyboard shortcut (`L`)
- A–Z jump nav pinned to right edge (`#` bucket for non-letter titles); dims unused letters
- Status breakdown chips in Library and itch.io summary rows (click to filter by status)
- Wishlist Deals tab sorts by post-sale price ascending (cheapest first)
- Deal discount badge styling tiers: ≥50% gradient glow, ≥75% animated gradient
- `enrich_steam_reviews.py --stores itch` backfills Steam review % on itch.io game-class rows
- `enrich_hltb.py` backfill script for any `games_*.json` row missing HLTB hours

### Changed

- Top-stats itch.io chip on Library tab shows videogame count only (not TTRPG/tools total)
- `refresh.ps1` clears log before run, includes itch Steam-review enrich step
- `.gitignore` covers Xbox, Battle.net, Nintendo, Ubisoft, GOG wishlist JSON outputs
- README documents all 11 data sources and enrichment scripts

### Added (earlier unreleased)

- Wishlist becomes a deal radar: dedicated drawer section with On sale only, Historical low only, Hide already-owned (cross-store), Min discount %, and Max price filters
- Default sort on first wishlist visit is Discount % desc, plus a deal-stat row count (e.g. "12 on sale, 3 at historical low")
- New "Wishlist Deals" Picks tab ranks wishlist items by deal score (discount + historical-low bonus + rating bonus, owned-elsewhere penalty); clicking a card switches view and focuses the row
- "+ Add game" modal grew an "Add to Wishlist" mode with optional price, discount %, and store URL fields, persisted via `manualGames` with a `wishlist: true` flag
- GOG wishlist fetcher (`fetch_gog_wishlist.py` → `games_wishlist_gog.json`) using the existing `GOG_AL` cookie; entries merge into the Wishlist tab with a GOG-tinted "WG" badge
- Wishlist row badges now indicate the target storefront (S/G/E/P/A/N/X/I/M)
- Wishlist polish: ITAD-aware Price sort, deal-aware CSV export, view-specific summary pills, library-only filter drawer sections, wishlist Tracking status column, Pick for me prefers on-sale items, manual discount-only entries pass max-price filter
- PlayStation library fetcher (`fetch_psn.py`, `psn_client.py`) using NPSSO token auth via `psnawp`
- PSN store filter chip, badge, and summary counts in the dashboard
- Trophy progress and platform tags on PSN rows
- itch.io owned-games fetcher (`fetch_itch.py`, `itch_client.py`) + dashboard chip/badge
- Slim toolbar with filter drawer, active filter pills, and kebab menu for data actions
- Personal free-form tags per game with filter chips, bulk tag add, picks integration, CSV export
- Bulk row selection with status/priority bar; cleanup mode filter; keyboard shortcuts
- Steam wishlist tab (`fetch_wishlist.py` → `games_wishlist.json`) with “already owned” hints
- IsThereAnyDeal prices (`fetch_itad.py`, `itad_client.py` → `itad_prices.json`) in Price column
- Cross-store cover backfill (`enrich_cross_store_images.py`) via Steam store search

## [0.3.0] - 2026-05-28

### Added

- GOG library fetcher (`fetch_gog.py`, `gog_client.py`) using session cookie auth
- Multi-store dashboard: load `games_steam.json` + `games_gog.json`, store filter chips, store badges
- Namespaced personal data keys (`steam:<id>` / `gog:<id>`) with automatic migration from v0.2

### Changed

- Steam fetcher writes `games_steam.json` and adds `store` / `id` fields on every game row
- Dashboard title and summary pills show per-store counts

## [0.2.0] - 2026-05-27

### Added

- Compact top layout with tabbed Picks panel (Top Rated, Next Up, Quick Wins, Hidden Gems)
- Pick-for-me randomizer, reload button, multi-select genre filters, and score column toggle
- Priority Score sorting, hidden-gem badge, status row colors, and persistent multi-row expansion
- Inline HLTB main-hour override and compact Main/Extra/Completionist display
- Price/discount support in `games.json` and Price column in the dashboard
- Weekly automation helper script (`refresh.ps1`) and updated README docs

## [0.1.0] - 2026-05-27

### Added

- Python fetcher for Steam library (owned games, store metadata, review scores)
- HowLongToBeat integration for game length estimates
- Local HTML dashboard with sort, filter, status, notes, and priority
- On-disk API cache for faster re-runs
- GitHub repo and local-only workflow (no hosting)
