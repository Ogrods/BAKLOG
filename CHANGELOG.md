# Changelog

All notable changes to this project are documented here.

This project follows [Semantic Versioning](https://semver.org/): MAJOR for
breaking changes, MINOR for backwards-compatible features, PATCH for
backwards-compatible bug fixes. The single source of truth for the current
version is `pyproject.toml` (mirrored into `package.json` and the
`<meta name="baklog-version">` tag in `index.html` for bug-bundle metadata).

## Release discipline

1. Land changes under `[Unreleased]` as they happen — categorize under Added /
   Changed / Fixed / Removed.
2. When cutting a release: bump `pyproject.toml` + `package.json`, rename the
   `[Unreleased]` block to `[X.Y.Z] - YYYY-MM-DD`, open a fresh
   `[Unreleased]` heading above it.
3. Tag the commit: `git tag -a vX.Y.Z -m "BAKLOG vX.Y.Z"` then
   `git push origin vX.Y.Z`. The tag is the install-reproducibility contract;
   without it, "which version do you have?" is unanswerable for a second
   contributor.

## [Unreleased]

### Added

- **Library count 1UP** — after a fetch adds games, the library / wishlist count rolls over ~1s with floating green "+N" popups (Mario 1UP / scrolling-combat-text style). Popups anchor on the right edge of the number, spawn ~70ms apart (up to 10 per burst) so several climb at once, and the rolling number uses `tabular-nums` so digits don't shift sideways as it counts. Only fires on fetch-driven *increases*, not filters or cold boot. Cancels cleanly on tab switch, view change, or `prefers-reduced-motion`. Chained fetcher landings (Steam, then GOG, then PSN) keep prior popups climbing instead of cutting them off mid-flight. Surfaces: Dashboard hero number and Library / Wishlist summary chips. Demos for screen recordings: load `index.html?demo=count` (six fake stores landing) or `?demo=count-small` (five `+1` bursts), or run `baklogDemoLibraryCount()` / `baklogDemoLibraryCountSmall()` from the console.
- **Portable secrets bundle** — passphrase-encrypted export/import of all Connections credentials plus Playwright profile dirs (`auth/bundle.py`, format version 1: magic `BAKLOGSB`, scrypt + AES-GCM). Dashboard: Connections ⋮ → Portable bundle… → Export / Import. API: `POST /api/auth/secrets/export` and `POST /api/auth/secrets/import`. CLI: `python -m auth export-bundle` / `import-bundle` (with `--dry-run`). Import snapshots existing profiles to `cache/auth/profiles_pre_import_<timestamp>/` before overwrite. See PRIVACY.md.
- **Local-only bug bundle** — sticky error toast and `?debug=1` overlay gain a "Copy bug bundle" button that puts a sanitized JSON payload on the clipboard (app version, view, data version, table fingerprint, filter count, last render time, session + persisted error log). Persisted log is a rolling 200-entry localStorage ring at `baklog-error-log`. Nothing is sent anywhere automatically. Kebab menu adds "Report a bug…" for the same bundle without needing a live error. See PRIVACY.md.
- **BAKLOG branding** — product title, favicon, README tagline, header subtitle (“Cross-store backlog · local-only”).
- **Deal badges** — price-dropped-since-last-ITAD (↓), all-time vs 1-year historical low, owned-elsewhere on dashboard deal cards.
- **Library cross-store pill** — “also on GOG · …” when deduped copies exist on multiple stores.
- **Export top 20 backlog** — ⋯ menu copies a Markdown table to clipboard.
- **Nintendo fetch** — clearer reconnect hint when session cookie expires (9001-1620).
- **Installer** — `dist/baklog` output folder and `Start BAKLOG.bat`.
- **Connections tab** — unified sign-in for all stores: form fields for API keys (Steam, Xbox, itch, ITAD), Playwright browser login for cookie/OAuth providers (GOG, PSN, Epic, Battle.net, Nintendo, Ubisoft), encrypted at rest via OS keychain + AES-GCM (`auth/` package).
- **Reconnect banner** when a fetcher fails auth (401/403) — links to Connections tab.
- **`scripts/build_installer.ps1`** — bundles app + Playwright Chromium into `dist/steam-backlog/`.

### Changed

- **Dashboard chart animation performance** — scatter no longer animates per-point colors; libraries over 200 points paint instantly; hover is rAF-throttled with spatial-hash hit tests (O(n) layout); line releases chart uses a shorter entrance; large scatter skips replay on tab revisit. CSS: huge-deal pulse uses opacity instead of filter; extended `prefers-reduced-motion` for fetcher/deal/scatter pulses.
- **Accessibility audit (bs_a11y)** — Lighthouse-aligned axe-core gate in CI (`tests/a11y/index-axe.test.js`); skip-to-main link + `<main id="main">`; focus trap/Escape on filter drawer, Connections popover, and modals; `aria-current` view tabs; co-op filter radiogroup pattern; contrast bump (`text-slate-500` → `text-slate-400` on slate-800); global `:focus-visible` outline. See [docs/a11y.md](docs/a11y.md).
- Fetch scripts read credentials from encrypted store first, then `.env` fallback (`auth.resolve_env`).

### Added (fetcher observability)

- **Fetcher observability hardening** — shared progress helpers (`fetchers/_progress.py`), start/end timing footers on all fetch/enrich scripts, heartbeats during long silent phases (HLTB cache skips, itch pagination, ITAD lookup, cover enrichment thread pool).
- **Server stall watchdog** — `server.py` emits `[server] no output for Ns — still running` when a subprocess is quiet for 30s (repeats every 60s).
- **`--allow-empty` flag** on GOG/Epic wishlist, Steam wishlist, Xbox, Epic library, GOG library, Steam library, PSN library, and ITAD fetchers — default refuses to overwrite JSON when zero items are returned (exit 2).
- **Reviews `--retry-misses`** — Shift+click on the Reviews chip re-attempts rows cached as no Steam app match (parity with HLTB/Covers).
- **Manifest `requires`** for Steam library, WL Steam, ITAD, and Reviews chips (missing-env warnings in Fetcher health).

### Changed

- HTTP failures in GOG wishlist product/price fetch, Steam cover search, Steam review search, and Ubisoft catalog batches now log status + URL instead of failing silently.
- HLTB enricher heartbeats during cached-miss skips as well as network lookups.

## [0.6.0] - 2026-05-30

### Added

- **`server.py` dev server** — replaces `python -m http.server` as the recommended
  way to run the dashboard on http://localhost:8765. Serves static files and
  exposes a small API: `POST /api/run/<key>` queues a fetcher, `GET
  /api/stream/<run_id>` streams stdout/stderr over SSE, `GET/PUT
  /api/personal` reads/writes `data/personal.json`. Runs are serialized through
  a single-worker queue; fetcher argv is whitelisted server-side.
- **Fetcher health row (dashboard)** — compact chip strip for all 15 data
  sources (stores, wishlists, ITAD, HLTB) with freshness coloring, entry
  counts, and an "Only stale / missing" toggle. When `server.py` is running,
  chips become buttons that enqueue the matching fetch script and open a live
  log panel below the row.
- **Server-backed personal data** — statuses, notes, priorities, tags, UI
  prefs, and manually-added games persist to `data/personal.json` (atomic
  writes + rolling backups in `data/personal_backups/`). Browser
  `localStorage` remains a hydration cache; server wins on boot. One-time
  migration banner offers to upload existing localStorage data when the server
  file is empty.
- **Filter drawer keyboard shortcuts footer** — always-visible two-row hint
  (`/` search, arrows, Enter, Esc, library status keys, priority, Space select)
  pinned to the bottom of the filter drawer.
- **Dashboard chart polish** — status/review donut palette tuned (backlog red,
  playing yellow, unfinished orange, finished green; Unreviewed grey); Top
  genres and Backlog hours by store unified (sorted bars, rounded ends, end
  labels, inline backlog legend); Releases by year switched to area chart with
  3-year rolling average and era bands; HLTB vs Steam rating scatter uses
  amber-to-emerald rating gradient; KPI strip adds Wishlist count and fits nine
  tiles on one row at xl widths.
- **Co-op spotlight (dashboard)** — replaced the old "Personal tags" bar chart
  with a full-width Co-op spotlight card laid out as a head-to-head versus:
  Online co-op on the left (blue-tinted side panel, blue-gradient hover) and
  Couch co-op on the right (emerald-tinted side panel, emerald-gradient
  hover), with a thin central unifier strip that shows Total co-op and Both
  flavors stats. Each side panel surfaces its own big count, Backlog /
  Finished / Avg HLTB numbers, and a three-row "Top unplayed picks" list
  (cover thumb, name, Steam rating %), all sorted by review score. The
  whole side panel is clickable (`role="button"` + Enter/Space keyboard
  support) to drill into the library with the matching co-op filter; the
  pick rows short-circuit the side click and focus the individual game
  instead. Empty-state copy guides the user back to `fetch_games.py` if no
  co-op flags are detected. The `dashDrillTag` helper and `chartTagsBar`
  block are gone (personal tags are still filterable via the drawer, just
  no longer charted on the dashboard).
- **Per-view sort persistence** — Library, Wishlist, and itch.io each now
  remember their last-used column sort across reloads. New `prefs.viewSorts`
  object stores `{ key, dir }` per view; the column header click handler
  persists it via a new `persistCurrentSort()` helper, and both
  `bootstrap()` and `switchView()` restore the right sort on entry through
  `applySavedSortForView()`. Also fixes a pre-existing cross-contamination
  bug: sorting Library by `hltb_main_hours` and then hopping to Wishlist no
  longer leaves Library stuck on `deal_price` when you come back. The old
  one-shot `wishlistSortVersion` migration is gone — wishlist's "cheapest
  first" preference is now just the default value of `viewSorts.wishlist`
  (`deal_price` asc), overrideable by any column click.
- **Co-op signal (Steam)** — `fetch_games.py` and `fetch_wishlist.py` now parse
  Steam's `categories` array into structured `coop_online` and `coop_local`
  booleans on every row. "Online Co-op" and "LAN Co-op" set `coop_online`;
  "Shared/Split Screen Co-op" sets `coop_local`. The bare "Co-op" category is
  intentionally ignored because the flavor is unknown. The category cap was
  also raised from `[:8]` to `[:16]` so co-op tags can't be silently truncated
  when a game ships with a lot of leading achievement/cloud-save flags.
  Existing JSON files (`games_steam.json`, `games_wishlist.json`) were
  backfilled in-place from the data already present in the `tags` array, so no
  refetch is required to see the new pills.
- **Co-op row pills** — the table title cell now renders a blue `ONLINE`
  pill and/or an emerald `COUCH` pill (right after the EA pill) whenever the
  matching co-op flag is set, mirroring the visual weight of the existing
  Early Access pill.
- **Co-op filter toggles** — the filter drawer gained a Co-op section with
  two checkboxes ("Online co-op", "Couch co-op"). Each acts as an AND filter
  (check both to require games that support *both* flavors), produces a
  matching active-filter pill ("Online co-op" / "Couch co-op"), and is
  cleared by both the per-pill × button and the Clear-all sweep. Filters
  feed into the same `table-query.js` worker pipeline as the rest of the
  drawer so the virtual table stays responsive.
- **Early Access filter toggle** — new "Early Access only" checkbox in the
  filter drawer (with an inline `EA` pill so its function is obvious). Hides
  every non-EA game across Library, Wishlist, and itch.io. Adds a matching
  active filter pill ("Early Access only") that the Clear-all sweep and the
  per-pill × button both reset. Detection reuses the same `isEarlyAccess`
  helper that drives the cover ribbon and table pill — now exported from
  `table-query.js` so the worker thread can use it too (the duplicate copy in
  `app.js` was removed to prevent drift).
- **Wishlist source filter chips** — the filter drawer now shows an "All ·
  Steam · GOG · Epic" chip row whenever the Wishlist tab is active (mirroring
  the Library tab's Store chips). Picking a chip filters the wishlist table
  by `wishlist_store`, adds a "Wishlist source: …" pill to the active filter
  bar, and persists across reloads via the `wishlistStoreFilter` pref. Manual
  wishlist entries still appear under "All".
- **Early Access badge** — games tagged "Early Access" (e.g. *Hyper Light
  Breaker*, *Slay the Spire 2*) now wear a Steam-style amber ribbon across the
  bottom of their cover art on the dashboard pick cards, deal hero card, and
  wishlist deal cards, plus a small `EA` pill next to the title in the main
  table. Detection is data-driven: any genre/tag containing "early access" or
  an explicit `early_access: true` flag triggers the badge — no extra fetch
  pass required.
- **Epic Games Store wishlist** fetcher (`fetch_epic_wishlist.py`) — uses the
  storefront session cookie (`EPIC_STORE_COOKIE` in `.env`) to query
  `www.epicgames.com/graphql`. Required because Epic discontinued
  `graphql.epicgames.com` and the launcher OAuth bearer can't reach the
  storefront. Results merge into the dashboard Wishlist tab and deal radar
  alongside Steam + GOG entries.
- `epic_client.EpicStoreClient` — cookie-based storefront GraphQL client.

### Changed

- **Dashboard `Top rated unplayed` and `Quick wins` rows are now clickable.**
  Each row in those two list cards is rendered as a button that calls
  `focusGame()` — clicking a game flips you to the Library tab, scrolls the
  matching row to the center of the table, and highlights it (same plumbing
  used by the deal hero and steals list).
- **Top deal card got a hero treatment.** The "Today's top deal" cover jumped
  from 52×78 to 92×138, the name now wraps to two lines instead of truncating,
  the price font is bumped, and a stat strip below the badges shows review%
  and HLTB main hours as pills with genres as plain text on a second line.
- **Wishlist deal cards fill their grid row.** All three dashboard deal cards
  now stretch to match the tallest column (driven by the steals list). The top
  deal meta column distributes name/price, badges, and stats top→middle→bottom;
  the sale scoreboard pins its cut-distribution bar to the card floor; the
  steals footer anchors to the bottom — so short and tall rows both look
  balanced instead of leaving dead space or crowded pill stacks.
- **Sale scoreboard stats are larger** and now include a **cut distribution**
  strip beneath the numbers: a horizontal stacked bar splitting wishlist sale
  items into Light (<25%) · Medium (25-49%) · Deep (50-74%) · Huge (75%+),
  with a labelled legend underneath showing each bucket's count. Lets you see
  at a glance whether your wishlist is full of mild sales or deep ones.
- **Wishlist deal cards revamped** — the dashboard's two scoreboard cards next
  to "Today's top deal" got real upgrades:
  - **Saved by waiting → Sale scoreboard.** The hypothetical "$70 you'd save
    if you bought everything" dollar figure was replaced by three actionable
    stats: `On sale 8 / 30`, `Avg cut -25%`, `Best cut -75%` (with the
    leading game's name as a caption). Click still drills to the
    on-sale-only wishlist view.
  - **Steals waiting → mini-list.** The big "4" + three thumbs were replaced
    with up to six clickable rows (cover · name · ★ if historical low · cut%
    · price). Each row jumps straight to that wishlist entry; the footer
    `+N more · view all →` still applies the steals filter (50%+ off or
    historical low, 80%+ rated).
- Wishlist row/pick badges now show the plain source-store letter (S/G/E/…)
  instead of a stacked `W*` glyph. The tooltip still reads "Wishlist · STORE".
- Dashboard itch.io recap pie chart now reflects the stats shown (rated games,
  unrated games, non-game items) instead of a personal-status breakdown.
- Header meta strip now consolidates wishlist counts into one entry
  (`Wishlist 30 (S 29 · G 0 · E 1)`) instead of three separate entries —
  scales as more stores are added.
- `state.libraryMeta` initial keys now cover every store (xbox, battlenet,
  ubisoft, wishlistGog, wishlistEpic, itad, hltb) for consistency.
- **Default local URL** — README and stack table now recommend
  `python server.py` → http://localhost:8765; plain `http.server` documented
  as read-only fallback.
- **`enrich_hltb.py`** — writes `fetched_at` into `cache/hltb_map.json` on
  save; dashboard HLTB fetcher-health chip falls back to the file's HTTP
  `Last-Modified` when the field is absent.

### Fixed

- **Bulk selection now works on Wishlist + itch.io tabs.** Previously the
  row-select checkboxes were rendered only when `activeView === "library"`
  and the bulk action bar refused to open elsewhere, so the column-header
  "select all visible" checkbox effectively no-op'd on those tabs. The per-row
  checkbox is now rendered in all table views and the bulk bar opens
  whenever there's at least one selection (any non-dashboard view).
- **Bulk status buttons now match the active tab.** The bottom bulk bar
  previously always showed all seven library statuses (Playing, Unfinished,
  Live service, …) even on Wishlist, where row dropdowns only offer Watching /
  Want it / Pass / Bought. Status buttons are rendered per view from shared
  label maps (`STATUS_LABELS` for Library + itch.io, `WISHLIST_STATUS_LABELS`
  for Wishlist) so bulk-set values always align with what each row can display.
- **"Select all visible" now visually checks every row.** The select-all and
  bulk-clear handlers updated `state.selectedKeys` but `renderTable()`
  short-circuited on the unchanged fingerprint, so the per-row boxes never
  re-painted. Each selection-mutation site (`selectAllVisible`, `bulkClear`,
  `bulkSetStatus`, `bulkSetPriority`) now calls `invalidateTableCache()`
  before re-rendering, so the table redraws with the new checkbox state.
- **HLTB enrichment now covers Xbox, Battle.net, Ubisoft, and Nintendo.**
  `enrich_hltb.py`'s `STORE_FILES` list was stale and silently skipped those
  four `games_*.json` files, leaving `hltb_main_hours` null on every entry.
  The Dashboard "Backlog hours by store" chart consequently showed empty bars
  for those stores. Added them to the loop so a single
  `python enrich_hltb.py` pass now backfills hours for all stores.
- **Dashboard wishlist cards no longer surface "fake" historical lows.**
  Newly released wishlist games whose price has never dropped were appearing
  in "Today's top deal" and "Steals waiting" because ITAD/Steam still reports
  `is_historical_low: true` for any never-discounted current price (e.g.
  *Mina the Hollower*, *MOUSE: P.I. For Hire*). `isStealDeal` and
  `wishlistGamesWithDeals` now require `cut > 0` first, so the dashboard only
  shows games that are genuinely on sale. The full wishlist tab still keeps
  the historical-low badge for those entries — it's just no longer flagged as
  a steal on the dashboard.
- **Fetcher SSE log panel on Windows** — `ConnectionAbortedError` when the
  browser closes an EventSource is handled gracefully; client reconnects to
  active/queued runs via `/api/runs` instead of showing a blank log.
- **Dashboard loading overlay** — `.dash-card { display: flex }` no longer
  overrides Tailwind `.hidden` on `#dashboardLoading`.
- **KPI row wrap** — nine KPI tiles stay on one row at xl (`xl:grid-cols-9`).

### Removed

- **Metacritic score** column, schema field (`metacritic_score`), and Steam
  `appdetails.metacritic` ingestion. Only Steam provided values, coverage was
  sparse (~10% of the Steam library; 0% of every other store), and the field
  doubled as a misleading signal next to Steam's own review %. Steam review %
  is now the single source of truth for rating. Existing
  `metacritic_score` fields are stripped from `games_*.json` on next fetch and
  the dashboard ignores any cached values.

## [0.5.1] - 2026-05-29

### Added

- Virtual scrolling for large tables (80+ rows): only visible rows are painted
- Web Worker filter/sort for libraries with 500+ games
- Shared row `<select>` templates and memoized `getPersonal()` lookups

### Changed

- `#tableWrap` is vertically scrollable with sticky header; compact `.row-ctl` selects
- Dashboard chart timers cancelled when leaving the dashboard tab (avoids stray renders)

## [0.5.0] - 2026-05-29

### Added

- **Phase 0 refactor:** `js/state.js` + `js/app.js` (ESM); dashboard logic moved out of inline `<script>`
- `shared/json_util.py` — strips null enrichment stubs when writing `games_*.json`
- `fetchers/_base.py` — shared fetcher helpers (stdout, HLTB/dry-run args, cache merge, JSON write)
- `enrichers` package — `python -m enrichers hltb|steam-reviews|cross-store-images`
- `pyproject.toml` + `tests/` (pytest for JSON slim + dedup name normalization)
- `tools/split_index_js.py` — re-extract script from HTML if needed

### Changed

- `fetch_itch.py` uses `fetchers._base` and slim JSON output

## [0.4.0] - 2026-05-29

### Added

- **Dashboard tab** (default view): Chart.js analytics with store/status/review donuts, genre and tag bars, backlog-hours-by-store stacked bar, HLTB histogram, releases timeline, HLTB-vs-rating scatter (log x-axis), wishlist deal stats, top-rated unplayed and quick-wins lists, itch.io recap card
- Per-view table render cache: instant tab switching when filters/sort/data unchanged
- `formatNum()` helper: comma-separates values with 5+ digits (KPIs, summary chips)
- PSN `psn_platforms` field; frontend `NON_GENRE_TOKENS` blocklist so platform labels never appear in genre charts
- itch.io fetcher merge preservation (`FETCHER_AUTHORITATIVE`, `_merge_cached_row`) and `--dry-run` flag

### Changed

- Score column toggle uses CSS class flip (`.table-hide-score`) instead of full table rerender
- Untouched games count as **Backlog** in status chips and dashboard donuts (removed misleading "No status" slice)
- HLTB histogram bars shade green→red by bucket; backlog-hours bars use store brand colors with bright cyan **Playing** segment
- itch.io recap moved into the 3-list row beside Quick wins; "Recently completed" card removed
- Dashboard legend labels use white text; custom backlog-hours legend uses `fontColor`
- `fetch_psn.py`: platforms stored in `psn_platforms`, not `genres`
- `fetch_games.py` writes only `games_steam.json` (dropped legacy `games.json` dual-write)
- File picker menu label: **Load Steam JSON…**
- Tailwind rebuilt with responsive variants (`md:`, `sm:`, `xl:`); removed dashboard `.dash-grid` workaround CSS
- Table render uses single `innerHTML` batch + delegated row-click handler

### Removed

- `enrich_steam_images.py` (superseded by `enrich_cross_store_images.py`)
- `patch_store_urls.py` (one-shot URL fix, complete)
- Legacy `games.json` auto-fetch fallback in dashboard

## [0.3.1] - 2026-05-29

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
- Price/discount support in store JSON and Price column in the dashboard
- Weekly automation helper script (`refresh.ps1`) and updated README docs

## [0.1.0] - 2026-05-27

### Added

- Python fetcher for Steam library (owned games, store metadata, review scores)
- HowLongToBeat integration for game length estimates
- Local HTML dashboard with sort, filter, status, notes, and priority
- On-disk API cache for faster re-runs
- GitHub repo and local-only workflow (no hosting)
