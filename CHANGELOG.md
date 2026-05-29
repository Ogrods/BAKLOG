# Changelog

All notable changes to this project are documented here.

## [Unreleased]

### Added

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
