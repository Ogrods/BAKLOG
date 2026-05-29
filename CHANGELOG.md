# Changelog

All notable changes to this project are documented here.

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
