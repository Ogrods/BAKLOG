# Steam Backlog Dashboard

![Dashboard preview](dashboard.png)

A **local-only** tool for browsing, sorting, and prioritizing your Steam library. Nothing is hosted on the web; your API key and library data stay on your machine.

## Stack

| Layer | Tech |
|-------|------|
| Data pipeline | Python 3 (`requests`, `python-dotenv`, `howlongtobeatpy`) |
| Data file | `games.json` (generated, gitignored) |
| Dashboard | Static HTML + vanilla JS + Tailwind (CDN) |
| Personal edits | Browser `localStorage` (status, notes, priority) |
| View locally | `python -m http.server 8080` → http://localhost:8080 |

## Features

- Tabbed Picks panel: Top Rated, Next Up, Quick Wins, Hidden Gems
- Smart sorting with optional Priority Score column
- Multi-select genre filters with AND/OR mode
- Pick-for-me randomizer and one-click `games.json` reload
- Inline HLTB override and compact Main/Extra/Completionist display
- Price and discount column sourced from Steam app details
- Status-aware row styling and hidden-gem badges

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

## Fetch your library

```bash
python fetch_games.py
```

First run may take several minutes for a large library (Steam Store API is rate-limited). Subsequent runs use cache and are much faster.

Options:

- `--refresh` — ignore cache, refetch everything
- `--only-new` — only fetch games not already in `games.json`
- `--appid 12345` — refetch a single game

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
| `fetch_games.py` | Fetches library data and writes `games.json` |
| `steam_client.py` | Steam Web API + Store API client |
| `hltb_client.py` | HowLongToBeat lookup |
| `index.html` | Dashboard UI |
| `games.json` | Generated game data (created by fetcher) |
| `cache/` | Cached API responses |
