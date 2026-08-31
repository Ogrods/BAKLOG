# Using the dashboard

BAKLOG runs at **http://localhost:8765** when you start `python server.py`. Four main tabs plus Connections organize your cross-store library.

## Tabs

| Tab | Purpose |
|-----|---------|
| **Dashboard** | Chart.js analytics (default view): KPI cards, store/status/review donuts, genre and tag charts, HLTB histogram, releases timeline, wishlist deal stats, top-rated and quick-wins lists, itch.io recap; plus a rotating marquee of 300+ stats and sabermetrics |
| **Library** | Deduped cross-store table of everything you own |
| **Wishlist** | Deal radar across connected wishlists plus **Claimable Now** free-game feed |
| **itch.io** | Quarantined indie library (hides tools/soundtracks/TTRPG PDFs by default; toggle to show all owned keys) |
| **Connections** | One-click store auth, encrypted credential storage, auto-refresh toggles, portable secrets bundle |

## Status chips

Click status breakdown chips in the summary row to filter:

**Backlog** · **Next** · **Playing** · **Unfinished** · **Live service** · **Finished** · **Skip**

Status-aware row styling and hidden-gem badges help surface what to play next.

## Picks panel

Tabbed picks on the dashboard and library views:

- Top Rated
- Next Up
- Quick Wins
- Hidden Gems
- Return To
- **Wishlist Deals**

## Filters and sorting

- Multi-select genre filters with AND/OR mode
- Store filter chips and store badges on multi-store rows
- Smart sorting with optional **Priority Score** column
- **Wishlist deal radar:** filter by On Sale / Historical Low / Min Discount % / Max Price; hide already-owned cross-store
- Pick-for-me randomizer and one-click JSON reload
- A-Z jump nav pinned to the right edge (xl+ screens)

## Column picker

Customize which columns appear in the library, wishlist, and itch tables:

1. Click the three-bar **Columns** button in the toolbar.
2. Toggle any data column (Cover, Score, Played, HLTB, Steam %, MC, Price, Released, Last played, Genres, Notes).
3. **Game** and **Status** columns are always visible.

Visibility persists per view in your personal prefs.

## Keyboard shortcuts

Open the filter drawer footer for shortcuts:

| Key | Action |
|-----|--------|
| `/` | Focus search |
| `↑` `↓` | Move selection |
| `Enter` | Open store page |
| `Esc` | Close drawer/modal |
| `B` `N` `P` `U` `L` `F` `S` | Set status (Library) |
| `Space` | Toggle row select |

## Library noise vs hidden list

Two different mechanisms keep the library clean:

| | **Library noise** (built-in) | **Hidden list** |
|---|---|---|
| What | Entries that are not games (store apps, DLC skins, soundtracks, entitlement slugs) | Real games you choose not to see |
| Who decides | Built into BAKLOG (`js/library-noise.js` / `shared/library_noise.py`) | You |
| How it applies | Fetchers write matching rows to the catalog with a `noise` tag; the dashboard auto-hides them on load | You hide a row, or defaults seed it on first run |
| Restorable | Yes - restore from **Hidden games** when the row is in the catalog | Yes - restore from **Hidden games** |

**Library noise** keeps non-games out of your counts and main view. The **hidden list** is your preference for real games you own but do not want front and center.

When library noise rows are auto-hidden, the library summary bar shows a **Filtered N non-games** chip. Click it to open the hidden-games panel filtered to auto-filtered entries only. Restore a row from there, or use **Not a game?** to report a false positive.

## Personal data storage

When you launch via `python server.py`, your statuses, notes, priorities, tags, UI prefs, and manually-added games persist to `data/personal.json` (or `profiles/<id>/data/personal.json` in multi-profile mode).

- The file is the source of truth - back it up, sync via Dropbox/OneDrive, or copy to another machine.
- The dev server writes atomically (temp file + rename) and keeps rolling timestamped backups in `data/personal_backups/`.
- Browser `localStorage` is a hot cache overwritten from `data/personal.json` on every boot. **Server wins.**

If you serve read-only via `python -m http.server`, the dashboard falls back to `localStorage`. Use **Export notes** / **Import notes** in the toolbar menu to back up. The first time you open via `server.py` after read-only mode, a banner offers to upload existing localStorage data into `data/personal.json`.

## Inline edits

- Inline HLTB override and compact Main/Extra/Completionist display
- Price and discount column from Steam app details (or ITAD when available)

## Paid tier highlights

Free forever to import and browse. Optional **$5/mo** ($50/yr) adds:

- No sponsored deal cards
- Scheduled stale-store refresh without keeping the app open
- Queued bulk refresh (every stale store in one sweep from Fetcher health)
- Deep achievement/trophy sync (full re-pull; free tier: cached % only)
- Bonus claimables feed (DLC, add-ons, in-game bonuses)

See [FAQ](faq.md) for the full free-vs-paid breakdown.

## Auto-behaviors

- **Auto-fetch on connect** (default on): when you connect or reconnect a store, BAKLOG auto-fetches its library and opens the fetcher log
- **Auto-refresh stale stores** (default on): quietly refreshes one store older than 24h every ~30 min while the app is open (Connections toggle)
- **Auto-enrich new games** (default off): after a library fetch adds games, optionally queues HLTB, reviews, covers, and co-op tags (Fetcher health toggle)
- **ITAD auto-refresh** (default on): deal prices refresh on a 15-60 min schedule while the dashboard is open

Details: [Refresh and enrichment](refresh-and-enrichment.md).
