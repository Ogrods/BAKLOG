# Steam Backlog Dashboard

![Dashboard preview](dashboard.png)

A **local-only** tool for browsing, sorting, and prioritizing game libraries across Steam, GOG, PlayStation, Epic, Amazon, Xbox, Battle.net, Ubisoft Connect, Nintendo Switch, and itch.io. Nothing is hosted on the web; your credentials and library data stay on your machine.

## Stack

| Layer | Tech |
|-------|------|
| Data pipeline | Python 3 (`requests`, `python-dotenv`, `howlongtobeatpy`, `psnawp`, store-specific clients) |
| Data files | `games_<store>.json` per source (generated, gitignored) |
| Dashboard | Static HTML + ESM (`js/state.js`, `js/app.js`) + prebuilt Tailwind (`tailwind.css`) + Chart.js (CDN) |
| Personal edits | `data/personal.json` via the dev server (status, notes, priority, tags, prefs, manual games); browser `localStorage` is the cache + fallback for read-only mode |
| View locally | `python server.py` → http://localhost:8765 (or `python -m http.server 8080` for read-only mode) |

## Features

- Four tabs: **Dashboard** (Chart.js analytics, default view), **Library** (deduped cross-store), **Wishlist** (deal radar), **itch.io** (quarantined indie library)
- Tabbed Picks panel: Top Rated, Next Up, Quick Wins, Hidden Gems, Return To, **Wishlist Deals**
- **Dashboard tab:** KPI cards, store/status/review donuts, genre and tag charts, HLTB histogram, releases timeline, wishlist deal stats, top-rated and quick-wins lists, itch.io recap; tab switches cache table renders for snappy navigation
- **itch.io tab:** hides tools/soundtracks/TTRPG PDFs by default; toggle to show all owned keys
- Status breakdown chips in the summary row (click to filter): Backlog, Next, Playing, Unfinished, Live service, Finished, Skip
- Smart sorting with optional Priority Score column
- Multi-select genre filters with AND/OR mode
- Pick-for-me randomizer and one-click JSON reload
- Inline HLTB override and compact Main/Extra/Completionist display
- Price and discount column sourced from Steam app details (or ITAD when available)
- Status-aware row styling and hidden-gem badges
- Multi-store dashboard with store filter chips and store badges
- A–Z jump nav pinned to the right edge (xl+ screens)
- **Wishlist deal radar:** filter by On Sale / Historical Low / Min Discount % / Max Price, hide already-owned cross-store

## Dashboard CSS (optional)

Tailwind is precompiled into `tailwind.css` (no browser JIT). After you change Tailwind classes in `index.html` (or `js/`), rebuild:

```bash
npm install
npm run build:css
```

## Setup

1. Install Python 3.10+ and create a virtual environment (optional but recommended):

   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. Get a [Steam Web API key](https://steamcommunity.com/dev/apikey) (use `localhost` as the domain).

3. Find your [SteamID64](https://steamid.io) (17-digit number starting with `7656119`).

4. Copy `.env.example` to `.env` and fill in credentials:

   ```bash
   copy .env.example .env
   ```

5. Set **Game details** to **Public** in Steam → Profile → Edit Profile → Privacy Settings.

## Fetch your libraries

**Steam:**

```bash
python fetch_games.py
```

Writes `games_steam.json`.

**GOG:** Sign in at [gog.com](https://www.gog.com), copy the `gog-al` cookie from DevTools → Application → Cookies, set `GOG_AL=` in `.env`, then:

```bash
python fetch_gog.py
```

**PlayStation (PSN):** Sign in at [playstation.com](https://www.playstation.com), open https://ca.account.sony.com/api/v1/ssocookie, copy the `npsso` token into `PSN_NPSSO=`, set trophy/game privacy to **Anyone**, then:

```bash
python fetch_psn.py
```

**Epic:** Run `python fetch_epic.py --auth-help` for OAuth steps. Paste the auth code into `EPIC_AUTH_CODE=` in `.env`, then:

```bash
python fetch_epic.py
```

**Amazon Games (Windows):** Reads the local Prime Gaming SQLite DB (DPAPI). Optional override: `AMAZON_GAMES_SQL_DIR=`.

```bash
python fetch_amazon.py
```

**Xbox / Game Pass / Microsoft Store:** Free key from https://xbl.io/ → `XBL_API_KEY=` in `.env`.

```bash
python fetch_xbox.py --skip-hltb
```

**Battle.net (unofficial):** Modern Edge / Chrome (v127+) use app-bound cookie encryption, so the automatic browser jar read usually fails on Windows even with admin. The reliable path is the manual `.env` cookie:

1. Sign in at [account.battle.net/games](https://account.battle.net/games) in Edge.
2. DevTools (F12) → Network → reload → click the `games-and-subs` request → copy the full `Cookie:` request header.
3. Paste it into `BATTLENET_COOKIE=` in `.env` (one line, no quotes).
4. Run:

```bash
python fetch_battlenet.py --browser env --skip-hltb
```

The session expires every few weeks; repeat steps 1–3 when you see a 401. Firefox's jar can be read without admin (`--browser firefox`) if you sign in there instead. `BATTLENET_BROWSER=env` makes `env` the default for future runs.

**Ubisoft Connect (unofficial):** Sign in at ubisoft.com, DevTools → Network → filter `public-ubi`, copy `Authorization` and `Ubi-SessionId` into `.env`.

```bash
python fetch_ubisoft.py --skip-hltb
```

**Nintendo Switch (unofficial):** Sign in at https://ec.nintendo.com/my/transactions/, copy the `Cookie` header from a transactions request into `NINTENDO_COOKIE=`. Only ~2 years of eShop history; cartridge games and older purchases must be added manually.

```bash
python fetch_nintendo.py --skip-hltb
```

**itch.io:** API key from https://itch.io/user/settings/api-keys → `ITCH_API_KEY=` in `.env`.

```bash
python fetch_itch.py --skip-hltb
python enrich_steam_reviews.py --stores itch
```

Writes all owned keys (games + tools/TTRPG PDFs). The dashboard itch.io tab hides non-games by default.

**Wishlist:**

```bash
python fetch_wishlist.py --skip-hltb
python fetch_gog_wishlist.py    # optional — needs GOG_AL; until run, WL GOG chip shows "missing"
python fetch_epic_wishlist.py
python fetch_itad.py
```

Wishlist JSON files (`games_wishlist.json`, `games_wishlist_gog.json`, `games_wishlist_epic.json`) are optional per store. The dashboard **Fetcher health** row marks any file that has not been fetched yet as *missing*; that is normal until you run the matching script.

**Epic wishlist (storefront cookie):** the wishlist lives behind storefront auth, separate from the launcher OAuth that `fetch_epic.py` uses. Sign in at [store.epicgames.com](https://store.epicgames.com), open the wishlist page, DevTools → Network → filter `graphql` → click any POST `/graphql` → Headers → Request Headers → copy the entire `Cookie:` value into `EPIC_STORE_COOKIE` in `.env`.

Fetcher options (all scripts):

- `--refresh` — ignore cache, refetch everything (Shift+click on supported library/wishlist chips)
- `--retry-misses` — re-attempt enricher rows cached as no match (Shift+click on HLTB, Reviews, Covers)
- `--only-new` — only fetch games not already in the store JSON file
- `--skip-hltb` — skip HowLongToBeat lookups (faster)
- `--allow-empty` — allow writing a zero-item result (default: refuse and exit 2 so stale data is preserved)
- Store-specific: `--appid`, `--id`, etc.

**Exit codes:** `0` success · `1` auth/config error · `2` suspicious empty result (or ITAD resolved zero titles). Every script prints `=== name started at … ===` and a footer summary with elapsed time.

**Stall watchdog:** when a fetcher runs via `server.py`, if stdout is silent for 30s the server injects `[server] no output for Ns — still running (PID …)` into the log panel (repeats every 60s). This is informational only — the process is not killed.

First Steam run may take several minutes for a large library (Store API is rate-limited). Subsequent runs use cache and are much faster.

## Enrichment scripts

| Script | Purpose |
|--------|---------|
| `enrich_steam_reviews.py` | Backfill Steam review % on non-Steam rows via Steam store search (gog, epic, psn, amazon, xbox, battlenet, ubisoft, nintendo, itch). Use `--stores nintendo` etc. to limit; Shift+click adds `--retry-misses`. |
| `enrich_cross_store_images.py` | Backfill `header_image` / `library_image` from the Steam CDN for non-Steam rows (gog, psn, epic, amazon, xbox, battlenet, ubisoft, nintendo). |
| `enrich_hltb.py` | Backfill HLTB hours on any `games_*.json` row missing them |
| `fetch_itad.py` | Cross-store deal prices → `itad_prices.json` (wishlist by default) |

## Open the dashboard

**Option A (recommended):** run the bundled dev server, which serves the dashboard *and* lets you trigger fetchers from the dashboard "Fetcher health" row:

```bash
python server.py
```

Then open http://localhost:8765 in your browser. Click any chip in the **Fetcher health** row to enqueue that fetcher — output streams live into a log panel and the chip refreshes when the run finishes. Enrichment chips **HLTB**, **Reviews** (`enrich_steam_reviews.py`), and **Covers** (`enrich_cross_store_images.py`) backfill non-Steam rows; **Steam** refreshes your owned Steam library. Runs are serialized (single-worker queue) so concurrent clicks won't corrupt shared caches. The server binds to `127.0.0.1` only; override with `PORT=9000 python server.py` to change the port. Restart `server.py` after editing `fetchers/manifest.json` so new chips register.

**Option B (read-only):** `python -m http.server 8080` if you only want to browse and prefer to run fetchers in your terminal.

**Option C:** open `index.html` directly and click **Load Steam JSON…** to pick a library file (browsers block automatic file loading when not using a server).

### Personal data storage

When you launch via `python server.py` (the recommended mode), your statuses, notes, priorities, tags, UI prefs, and manually-added games are persisted to `data/personal.json`. The file is the source of truth — back it up, sync it via Dropbox/OneDrive/git, copy it to another machine. The dev server writes atomically (temp file + rename) and keeps a rolling set of timestamped backups in `data/personal_backups/` so a bad save can't wipe earlier edits.

The browser's `localStorage` still exists as a hot cache that the page hydrates from on first paint, but it is overwritten from `data/personal.json` on every boot. **Server wins.**

If you instead serve the dashboard read-only via `python -m http.server`, the dashboard falls back to localStorage as in earlier versions and the **Export notes** / **Import notes** buttons (in the toolbar ⋯ menu) become the only way to back up. The first time you open the dashboard via `server.py` after using read-only mode, a banner offers to upload your existing localStorage data into `data/personal.json`.

## Auto-refresh on a schedule (Windows)

Use the included `refresh.ps1` helper:

```powershell
Set-Location "c:\Users\DanOg\Documents\My Docs\Coding Stuff\steam-backlog"
.\refresh.ps1
```

Create a weekly scheduled task (example: Sundays at 9:00):

```powershell
schtasks /create /SC WEEKLY /D SUN /TN "Steam Backlog Refresh" /TR "powershell -ExecutionPolicy Bypass -File \"c:\Users\DanOg\Documents\My Docs\Coding Stuff\steam-backlog\refresh.ps1\"" /ST 09:00
```

## Files

| File | Purpose |
|------|---------|
| `fetch_games.py` | Steam library → `games_steam.json` |
| `fetch_gog.py` | GOG library → `games_gog.json` |
| `fetch_psn.py` | PSN library → `games_psn.json` |
| `fetch_epic.py` | Epic library → `games_epic.json` |
| `fetch_amazon.py` | Amazon Prime Gaming → `games_amazon.json` |
| `fetch_xbox.py` | Xbox / Game Pass / MS Store → `games_xbox.json` |
| `fetch_battlenet.py` | Battle.net → `games_battlenet.json` |
| `fetch_ubisoft.py` | Ubisoft Connect → `games_ubisoft.json` |
| `fetch_nintendo.py` | Nintendo eShop (~2yr) → `games_nintendo.json` |
| `fetch_itch.py` | itch.io owned keys → `games_itch.json` |
| `fetch_wishlist.py` | Steam wishlist → `games_wishlist.json` |
| `fetch_gog_wishlist.py` | GOG wishlist → `games_wishlist_gog.json` |
| `fetch_epic_wishlist.py` | Epic Games Store wishlist → `games_wishlist_epic.json` (uses `EPIC_STORE_COOKIE`) |
| `fetch_itad.py` | IsThereAnyDeal prices → `itad_prices.json` |
| `enrich_steam_reviews.py` | Backfill Steam review fields on non-Steam rows |
| `enrich_cross_store_images.py` | Backfill GOG/PSN/Epic/Amazon covers from Steam CDN |
| `enrich_hltb.py` | Backfill HLTB hours on any store JSON |
| `python -m enrichers <cmd>` | Wrapper: `hltb`, `steam-reviews`, `cross-store-images` |
| `shared/`, `fetchers/` | Shared JSON slim + fetcher base helpers |
| `js/state.js`, `js/app.js` | Dashboard app (ES modules) |
| `steam_client.py` | Steam Web API + Store API client |
| `gog_client.py` | GOG embed API client |
| `psn_client.py` | PlayStation Network client (via psnawp) |
| `epic_client.py` | Epic OAuth client |
| `amazon_client.py` | Amazon Games SQLite reader |
| `xbox_client.py` | OpenXBL title history client |
| `battlenet_client.py` | Battle.net session (Edge cookie jar + optional .env fallback) |
| `ubisoft_client.py` | Ubisoft Connect API client |
| `nintendo_client.py` | Nintendo eShop transactions client |
| `itch_client.py` | itch.io API client |
| `itad_client.py` | IsThereAnyDeal API client |
| `hltb_client.py` | HowLongToBeat lookup |
| `index.html` | Dashboard UI (loads all store JSON files) |
| `games_*.json`, `itad_prices.json` | Generated per-store data (gitignored) |
| `cache/` | Cached API responses |

## Project layout

The repo keeps most scripts in the project root on purpose — each fetcher is a standalone entry point you run directly.

| Pattern | What it is |
|---------|------------|
| `fetch_*.py` | One script per store; writes `games_<store>.json` |
| `*_client.py` | HTTP/auth helpers used by fetchers |
| `enrich_*.py` | Backfill or maintenance scripts |
| `games_*.json`, `itad_prices.json` | Generated library data (gitignored where applicable) |
| `index.html`, `js/`, `tailwind.css` | Static dashboard (serve over HTTP for ES modules) |
| `cache/` | Cached API responses between fetch runs |
| `refresh.ps1` | Runs the fetch sequence in order |

No nested `src/` folder — run fetchers from the repo root so paths stay simple.

### Dev checks

```bash
pip install -e ".[dev]"
python -m pytest
ruff check shared fetchers enrichers tests
```

Phase 0 is **local-only** — no cloud accounts or billing. Supabase/Next.js (Phase 1) stays on the roadmap until you opt in.
