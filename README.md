# Steam Backlog Dashboard

![Dashboard preview](dashboard.png)

A **local-only** tool for browsing, sorting, and prioritizing your game libraries (Steam, GOG, and PlayStation). Nothing is hosted on the web; your credentials and library data stay on your machine.

## Stack

| Layer | Tech |
|-------|------|
| Data pipeline | Python 3 (`requests`, `python-dotenv`, `howlongtobeatpy`, `psnawp`) |
| Data files | `games_steam.json`, `games_gog.json`, `games_psn.json` (generated, gitignored) |
| Dashboard | Static HTML + vanilla JS + prebuilt Tailwind (`tailwind.css`) |
| Personal edits | Browser `localStorage` (status, notes, priority) |
| View locally | `python -m http.server 8080` → http://localhost:8080 |

## Features

- Tabbed Picks panel: Top Rated, Next Up, Quick Wins, Hidden Gems, Return To, **Wishlist Deals**
- Smart sorting with optional Priority Score column
- Multi-select genre filters with AND/OR mode
- Pick-for-me randomizer and one-click `games.json` reload
- Inline HLTB override and compact Main/Extra/Completionist display
- Price and discount column sourced from Steam app details (or ITAD when available)
- Status-aware row styling and hidden-gem badges
- Multi-store dashboard with Steam / GOG / PSN filters and store badges
- **Wishlist deal radar:** filter by On Sale / Historical Low / Min Discount % / Max Price, hide already-owned cross-store, and add wishes manually for any storefront

## Dashboard CSS (optional)

Tailwind is precompiled into `tailwind.css` (no browser JIT). After you change Tailwind classes in `index.html`, rebuild:

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

4. Copy `.env.example` to `.env` and fill in your key and Steam ID:

   ```bash
   copy .env.example .env
   ```

5. Set **Game details** to **Public** in Steam → Profile → Edit Profile → Privacy Settings.

## Fetch your libraries

**Steam:**

```bash
python fetch_games.py
```

Writes `games_steam.json` (and a legacy `games.json` copy for compatibility).

**GOG:**

1. Sign in at [gog.com](https://www.gog.com) in your browser.
2. Open DevTools (F12) → **Application** → **Cookies** → `https://www.gog.com`.
3. Copy the value of the `gog-al` cookie into `.env` as `GOG_AL=...`.
4. Run:

```bash
python fetch_gog.py
```

Writes `games_gog.json`. The cookie expires about every 30 days; re-copy it when fetches fail with an auth error.

GOG playtime in the dashboard only appears if you use **GOG Galaxy 2.0** and have played the game through Galaxy.

**PlayStation (PSN):**

1. Sign in at [playstation.com](https://www.playstation.com) in your browser (same browser tab/session).
2. Open this URL in a **new tab** (while still signed in):

   **https://ca.account.sony.com/api/v1/ssocookie**

   You should see JSON like `{"npsso":"<64-character-token>"}`. Copy the token value only (not the quotes or braces).
3. Paste into `.env` as `PSN_NPSSO=...`

   **Alternative:** DevTools → Application → Cookies → **`https://ca.account.sony.com`** (not playstation.com) → look for cookie named `npsso`.

4. Set **Trophies** and **Games** to **Anyone** in PSN privacy settings (Settings → Account Management → Privacy Settings).
5. Run:

```bash
python fetch_psn.py
```

Writes `games_psn.json`. The NPSSO token expires periodically; re-copy it when fetches fail with an auth error.

PSN playtime comes from Sony's title-stats API (PS4/PS5 only). PS3/Vita titles show trophy progress but usually no hour counts. Unplayed owned PS4/PS5 games are included via entitlements.

Fetcher options (all scripts):

- `--refresh` — ignore cache, refetch everything
- `--only-new` — only fetch games not already in the store JSON file
- `--skip-hltb` — skip HowLongToBeat lookups (faster)
- Steam: `--appid 12345` · GOG: `--id 1234567890` · PSN: `--id NPWR12345_00`

First Steam run may take several minutes for a large library (Store API is rate-limited). Subsequent runs use cache and are much faster.

## Open the dashboard

**Option A (recommended):** run a local server from this folder:

```bash
python -m http.server 8080
```

Then open http://localhost:8080 in your browser.

**Option B:** open `index.html` directly and click **Load games.json** to pick the file (browsers block automatic file loading when not using a server).

Personal notes, status, and priority are stored in your browser's localStorage. Use **Export notes** in the dashboard to back them up.

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
| `fetch_games.py` | Fetches Steam library → `games_steam.json` |
| `fetch_gog.py` | Fetches GOG library → `games_gog.json` |
| `fetch_psn.py` | Fetches PSN library → `games_psn.json` |
| `fetch_itch.py` | itch.io owned games → `games_itch.json` (`ITCH_API_KEY` in `.env`) |
| `fetch_wishlist.py` | Steam wishlist → `games_wishlist.json` (public wishlist + `STEAM_API_KEY`) |
| `fetch_gog_wishlist.py` | GOG wishlist → `games_wishlist_gog.json` (uses `GOG_AL` cookie; `--hltb` for HLTB lookup) |
| `fetch_itad.py` | IsThereAnyDeal prices → `itad_prices.json` (`ITAD_API_KEY` in `.env`) |
| `enrich_cross_store_images.py` | Backfill GOG/PSN/Epic/Amazon covers from Steam CDN |
| `steam_client.py` | Steam Web API + Store API client |
| `gog_client.py` | GOG embed API client |
| `psn_client.py` | PlayStation Network client (via psnawp) |
| `hltb_client.py` | HowLongToBeat lookup |
| `index.html` | Dashboard UI (loads all store JSON files) |
| `games_steam.json` / `games_gog.json` / `games_psn.json` | Generated per-store data |
| `cache/` | Cached API responses |
