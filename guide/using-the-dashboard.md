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

## Blacklist vs hidden list

Two different mechanisms keep the library clean:

| | **Blacklist** | **Hidden list** |
|---|---|---|
| What | Entries that aren't games (store apps, DLC skins, soundtracks, internal entitlement slugs) | Real games you choose not to see |
| Who decides | Built into BAKLOG | You |
| Editable | No - never shown, can't be restored | Yes - restore from the **Hidden games** panel |

The **blacklist** removes noise that is never a game. The **hidden list** is your preference for games you own but don't want in the main view.

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
- Deep achievement/trophy sync (full re-pull; free tier: cached % only)
- Bonus claimables feed (DLC, add-ons, in-game bonuses)

See [FAQ](faq.md) for the full free-vs-paid breakdown.

## Auto-behaviors (default on)

- **Auto-fetch on connect:** when you connect or reconnect a store, BAKLOG auto-fetches its library and opens the fetcher log
- **Auto-refresh stale stores:** quietly refreshes one store older than 24h every ~30 min while the app is open (Connections toggle)
- **Auto-enrich:** after a library fetch adds games, queues HLTB, reviews, covers, and co-op tags
- **ITAD auto-refresh:** deal prices refresh on a 15-60 min schedule while the dashboard is open

Details: [Refresh and enrichment](refresh-and-enrichment.md).
