# BAKLOG

**Cross-store game backlog — local-only.**

![Dashboard preview](dashboard.png)

BAKLOG helps you browse, sort, and prioritize games across Steam, GOG, PlayStation, Epic, Amazon, Xbox, Battle.net, Ubisoft Connect, Nintendo Switch, and itch.io. Nothing is hosted on the web; your credentials and library JSON stay on your machine.

> Formerly “Steam Backlog Dashboard” — same repo, sharper name for a multi-store product.

See [PRIVACY.md](PRIVACY.md) for the data-handling story (TL;DR: nothing leaves your machine) and [SECURITY.md](SECURITY.md) for the threat model (TL;DR: there is no server to breach). Released under the [MIT license](LICENSE).

## Supported platforms

| OS | Status |
|----|--------|
| **Windows 10/11** | Fully supported (primary development target) |
| **macOS** | Supported with limits — every store except **Amazon Games** |
| **Linux** | Supported with limits — every store except **Amazon Games** |

The app itself (dashboard, `server.py`, secret storage, browser sign-in) is OS-agnostic. The one Windows-only source is **Amazon Games**: it reads the desktop launcher's local SQLite database, which is encrypted with Windows DPAPI and has no portable equivalent. On macOS/Linux, Amazon is shown as **Unavailable** in Connections and its fetcher chip is disabled — everything else works the same.

Credentials are stored via your OS **keyring** (Windows Credential Manager, macOS Keychain, Linux Secret Service) with an AES-GCM file fallback — not DPAPI. See [`auth/secrets.py`](auth/secrets.py).

**Requirements (all platforms):** Python 3.11+, Google Chrome or Chromium for the Connect sign-in flow (override with `BAKLOG_CHROME_PATH`), then `pip install -e ".[dev]"` and `python server.py`.

### Store availability by platform

| Store | Windows | macOS / Linux |
|-------|:-------:|:-------------:|
| Steam, GOG, PSN, Epic, Xbox, Battle.net, Ubisoft, Nintendo, itch.io, Humble, EA, ITAD | Yes | Yes |
| Amazon Games | Yes | No (Windows-only launcher DB) |

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

### Local profiles (optional)

Use the **profile menu** in the header (next to the logo) for separate datasets — e.g. work vs play. Until you add a second profile, everything stays in the repo root as today. The first **Create** copies your current `games_*.json`, `data/`, and `cache/auth/` into `profiles/default/` (root files remain as backup) and starts the new profile empty. Switching profiles reloads the app. CLI fetchers respect `BAKLOG_PROFILE=<id>` or the active entry in `profiles/index.json`. Rollback: delete the `profiles/` folder to return to legacy single-root layout.

## Fetch your libraries

**Recommended:** run `python server.py`, open **Connections**, and click **Connect** for each store. A headed Chrome/Edge window opens for cookie/OAuth sign-in; credentials stay local in `cache/auth/`. Then run fetchers from the dashboard **Fetcher health** row or from the terminal below.

**Steam:** Connections → Steam → Connect (grabs your API key automatically), or set `STEAM_API_KEY` + `STEAM_ID` in `.env` manually. Set **Game details** to **Public** in Steam profile privacy.

```bash
python fetch_games.py
```

Writes `games_steam.json`.

**GOG:** Connections → GOG → Connect and sign in at [gog.com](https://www.gog.com). One sign-in covers library + wishlist.

```bash
python fetch_gog.py
```

*Fallback:* copy the `gog-al` cookie from DevTools → Application → Cookies into `GOG_AL=` in `.env`.

**PlayStation (PSN):** Connections → PlayStation → Connect and sign in at the PlayStation Store. Set trophy/game privacy to **Anyone** so the library and wishlist can load.

```bash
python fetch_psn.py
```

*Fallback:* open https://ca.account.sony.com/api/v1/ssocookie while logged in and paste the `npsso` token into `PSN_NPSSO=` in `.env`.

**Epic (library):** Connections → Epic (library) → Connect — we capture and exchange the authorization code automatically.

```bash
python fetch_epic.py
```

*Fallback:* run `python fetch_epic.py --auth-help` and paste the code into `EPIC_AUTH_CODE=` in `.env`.

**Epic (wishlist):** Connections → Epic (wishlist) → Connect on the storefront (separate session from library).

```bash
python fetch_epic_wishlist.py
```

**Amazon Games (Windows):** No browser sign-in — reads the Prime Gaming launcher SQLite DB on this PC. Optional override: `AMAZON_GAMES_SQL_DIR=`.

```bash
python fetch_amazon.py
```

**Xbox (play history):** Connections → Xbox → Connect at [xbl.io](https://xbl.io/login), or paste an OpenXBL API key into the card.

```bash
python fetch_xbox.py --skip-hltb
```

**Xbox Store wishlist:** Connections → Xbox Store wishlist → Connect on xbox.com (separate from play history above).

```bash
python fetch_xbox_wishlist.py
```

**Battle.net (unofficial):** Connections → Battle.net → Connect and sign in at [account.battle.net](https://account.battle.net/). The managed browser saves your session cookie locally; the fetcher uses it automatically (`--browser env` when a stored cookie exists).

```bash
python fetch_battlenet.py --skip-hltb
```

*Fallback (if Connect fails or you prefer CLI-only):* DevTools → Network → `games-and-subs` → copy the full `Cookie:` header into `BATTLENET_COOKIE=` in `.env`, then `python fetch_battlenet.py --browser env --skip-hltb`. On Windows, Edge/Chrome v127+ app-bound encryption can block the legacy *fetch-time* browser-jar read (`--browser edge`); Connect + stored cookie avoids that. Firefox (`--browser firefox`) or the `.env` cookie path still work without admin.

**Ubisoft Connect (unofficial):** Connections → Ubisoft Connect → Connect (one sign-in for library + Ubisoft Store wishlist).

```bash
python fetch_ubisoft.py --skip-hltb
python fetch_ubisoft_wishlist.py
```

*Fallback:* DevTools → Network → `public-ubi` → copy `Authorization` and `Ubi-SessionId` into `.env`.

**Nintendo (eShop library):** Connections → Nintendo → Connect. Only ~2 years of digital eShop history; cartridge games and older purchases must be added manually.

```bash
python fetch_nintendo.py --skip-hltb
```

*Fallback:* copy the `Cookie` header from a `ec.nintendo.com/my/transactions` request into `NINTENDO_COOKIE=` in `.env`.

**Nintendo Store wishlist:** Connections → Nintendo Store wishlist → Connect on nintendo.com.

```bash
python fetch_nintendo_wishlist.py
```

**EA App:** Connections → EA App → Connect at ea.com.

```bash
python fetch_ea.py
```

**Humble Bundle:** Connections → Humble Bundle → Connect at humblebundle.com (library page). One profile unlocks library + store wishlist fetchers.

```bash
python fetch_humble.py --skip-hltb
python fetch_humble_wishlist.py
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
python fetch_nintendo_wishlist.py   # Connections → Nintendo Store wishlist (separate from eShop library login)
python fetch_itad.py
```

Wishlist JSON files (`games_wishlist.json`, `games_wishlist_gog.json`, `games_wishlist_epic.json`, `games_wishlist_nintendo.json`, etc.) are optional per store. The dashboard **Fetcher health** row marks any file that has not been fetched yet as *missing*; that is normal until you run the matching script.

**Epic wishlist:** separate from launcher OAuth (`fetch_epic.py`). Connections → **Epic (wishlist)** → Connect at [store.epicgames.com/wishlist](https://store.epicgames.com/en-US/wishlist) (clear Cloudflare if shown). `fetch_epic_wishlist.py` reuses the saved browser profile headlessly — no `EPIC_STORE_COOKIE` paste.

Fetcher options (all scripts):

- `--refresh` — ignore cache, refetch everything (Shift+click on supported library/wishlist chips)
- `--retry-misses` — re-attempt enricher rows cached as no match (Shift+click on HLTB, Reviews, Covers)
- `--only-new` — only fetch games not already in the store JSON file
- `--skip-hltb` — skip HowLongToBeat lookups (faster)
- `--allow-empty` — allow writing a zero-item result (default: refuse and exit 2 so stale data is preserved)
- Store-specific: `--appid`, `--id`, etc.

**Exit codes:** `0` success · `1` runtime/config error · `2` suspicious empty result (or ITAD resolved zero titles) · `3` drift guard refused write · `4` auth failure (expired/invalid credential). Every script prints `=== name started at … ===` and a footer summary with elapsed time.

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
pip install -r requirements.txt
python server.py
```

Requires **Google Chrome** or **Microsoft Edge** installed (Edge ships with Windows). Connections opens a headed browser window for cookie/OAuth sign-in. Override the browser path with `BAKLOG_CHROME_PATH` if needed.

On Windows, prefer the project venv interpreter (`.venv\Scripts\python.exe server.py`) rather than the Microsoft Store `python.exe` stub. Fetcher subprocesses launched from the stub can hang `subprocess.Popen` and wedge the run queue.

**Connections tab:** sign in once per store from the dashboard — API keys via form fields, cookie/OAuth stores via a headed Chrome/Edge window. Credentials are encrypted in `cache/auth/` (OS keychain by default). `.env` still works as a fallback.

#### Moving to a new machine

1. On the old machine: **Connections** → ⋮ → **Portable bundle…** → **Export bundle…**. Choose a passphrase and save the downloaded `baklog-secrets-*.bundle` somewhere safe (USB, cloud folder, etc.).
2. Install BAKLOG on the new machine (`pip install -r requirements.txt`, `python server.py`). Chrome or Edge must be installed for Connections sign-in.
3. **Connections** → ⋮ → **Portable bundle…** → **Import bundle…**, pick the file, enter the same passphrase. The page reloads with every provider restored — including browser cookie profiles.

Terminal alternative:

```bash
python -m auth export-bundle --out baklog-secrets.bundle
python -m auth import-bundle baklog-secrets.bundle
```

See [PRIVACY.md](PRIVACY.md#portable-secret-bundle) for what's inside the bundle and [SECURITY.md](SECURITY.md) for the full threat model.

Then open http://localhost:8765 in your browser. Click any chip in the **Fetcher health** row to enqueue that fetcher — output streams live into a log panel and the chip refreshes when the run finishes.

**Option B (read-only):** `python -m http.server 8080` if you only want to browse and prefer to run fetchers in your terminal.

**Option C:** open `index.html` directly (browsers block automatic local file loading without a server — use Option A or B for the full experience).

### Reporting a bug

When something goes wrong, BAKLOG captures uncaught errors and unhandled
promise rejections automatically and surfaces a sticky red toast in the
top-right corner. Three buttons:

- **Copy bug bundle** — assembles a sanitized JSON payload (errors + app
  context: version, view, data version, filter count, table fingerprint,
  last render time, dashboard counters) and copies it to your clipboard.
  Paste it into a [new GitHub issue](https://github.com/Ogrods/steam-backlog/issues/new). Nothing is sent anywhere by the app — what you do with the
  clipboard is up to you. Personal notes, library JSON, and credentials are
  never included (see [PRIVACY.md](PRIVACY.md#error-logs-and-bug-reporting) for
  the full whitelist).
- **Errors only** — copies just the error array, without app context.
- **Details** — expand the stack trace inline.

The last 200 errors are kept in browser `localStorage` so the bundle can
include history across reloads. Clear the ring with
`localStorage.removeItem('baklog-error-log')` in DevTools.

### Personal data storage

When you launch via `python server.py` (the recommended mode), your statuses, notes, priorities, tags, UI prefs, and manually-added games are persisted to `data/personal.json`. The file is the source of truth — back it up, sync it via Dropbox/OneDrive/git, copy it to another machine. The dev server writes atomically (temp file + rename) and keeps a rolling set of timestamped backups in `data/personal_backups/` so a bad save can't wipe earlier edits.

The browser's `localStorage` still exists as a hot cache that the page hydrates from on first paint, but it is overwritten from `data/personal.json` on every boot. **Server wins.**

If you instead serve the dashboard read-only via `python -m http.server`, the dashboard falls back to localStorage as in earlier versions and the **Export notes** / **Import notes** buttons (in the toolbar ⋯ menu) become the only way to back up. The first time you open the dashboard via `server.py` after using read-only mode, a banner offers to upload your existing localStorage data into `data/personal.json`.

## Auto-refresh on a schedule

The cross-platform way to run fetchers is from the UI — click any chip in the **Fetcher health** row. For unattended refreshes, use the helper script for your OS. Both run the same fetch sequence and log to `refresh.log`.

**Windows** (`refresh.ps1`):

```powershell
Set-Location "c:\Users\DanOg\Documents\My Docs\Coding Stuff\steam-backlog"
.\refresh.ps1
```

Create a weekly scheduled task (example: Sundays at 9:00):

```powershell
schtasks /create /SC WEEKLY /D SUN /TN "BAKLOG Refresh" /TR "powershell -ExecutionPolicy Bypass -File \"c:\Users\DanOg\Documents\My Docs\Coding Stuff\steam-backlog\refresh.ps1\"" /ST 09:00
```

**macOS / Linux** (`refresh.sh`):

```bash
chmod +x refresh.sh   # first time only
./refresh.sh
```

Schedule it weekly with `cron` (example: Sundays at 9:00):

```bash
crontab -e
# then add:
0 9 * * 0 cd /path/to/steam-backlog && ./refresh.sh
```

> `refresh.sh` skips `fetch_amazon.py` automatically — that store is Windows-only.

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
| `fetch_humble.py` | Humble Bundle library (games only) → `games_humble.json` |
| `fetch_itch.py` | itch.io owned keys → `games_itch.json` |
| `fetch_wishlist.py` | Steam wishlist → `games_wishlist.json` |
| `fetch_gog_wishlist.py` | GOG wishlist → `games_wishlist_gog.json` |
| `fetch_epic_wishlist.py` | Epic Games Store wishlist → `games_wishlist_epic.json` |
| `fetch_humble_wishlist.py` | Humble Store wishlist → `games_wishlist_humble.json` |
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
| `amazon_client.py` | Amazon Games SQLite reader (Windows-only) |
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
| `refresh.ps1` / `refresh.sh` | Runs the fetch sequence in order (Windows / POSIX) |

No nested `src/` folder — run fetchers from the repo root so paths stay simple.

### Dev checks

```bash
pip install -e ".[dev]"
python -m pytest
ruff check shared fetchers enrichers tests
```

**Connections CDP smoke test** (requires Chrome or Edge; not run in default CI):

```bash
pytest tests/test_cdp_browser.py -m integration
```

On GitHub, use **Actions → CDP smoke (manual) → Run workflow** after a suspected Chrome/Edge regression.

Phase 0 is **local-only** — no cloud accounts or billing. Supabase/Next.js (Phase 1) stays on the roadmap until you opt in.
