# Getting started

Install BAKLOG, run the local server, and open the dashboard in your browser.

## Requirements

| Requirement | Notes |
|-------------|-------|
| **Python 3.11+** | Use a virtual environment (recommended) |
| **Google Chrome or Chromium** | Required for the Connections sign-in flow. Microsoft Edge also works on Windows. Override with `BAKLOG_CHROME_PATH` if needed |
| **OS** | Windows 10/11 (primary), macOS, or Linux - see [FAQ](faq.md#supported-platforms) for store limits |

On Windows, use the project `.venv` Python - not the Microsoft Store `python.exe` stub. Fetcher subprocesses launched from the stub can hang and wedge the run queue. `server.py` auto-picks `.venv` when present.

## Beta (Windows)

If you received a beta invite:

1. Download and run **BAKLOG-Setup.exe** from your invite link.
2. If SmartScreen warns about an unknown publisher, click **More info**, then **Run anyway**.
3. Launch **BAKLOG** from the Start Menu. A tray icon appears and your browser opens.
4. Open the **Connections** tab and connect each store you use (Chrome or Edge required).

Your library data (profiles, games, connections) lives in `%LOCALAPPDATA%\BAKLOG-Data`, separate from the app folder. Uninstalling BAKLOG removes the app and always clears login autostart; the uninstall wizard lets you keep your library or remove everything (data folder and saved sign-ins).

**Maintainers testing dev and frozen on one PC:** optional `BAKLOG_DATA_DIR=%LOCALAPPDATA%\BAKLOG-Dev` in `.env` keeps `python server.py` out of the installer's data folder. The dashboard header shows a **Dev server** chip when the dev server is active. See [troubleshooting](troubleshooting.md#dev-server-vs-frozen-exe-same-browser-origin).

Portable zip builds work too: unzip to a normal folder, then run `Start BAKLOG.bat` or `BAKLOG Tray.exe`. Add an empty `portable.txt` beside `BAKLOG.exe` only if you want all data in the unzip folder (thumb drives). See `BETA-README.txt` in the bundle.

## Install (from source)

1. Clone or download the repo from [GitHub](https://github.com/Ogrods/BAKLOG).

2. Create a virtual environment and install dependencies:

   ```bash
   python -m venv .venv
   .venv\Scripts\activate          # Windows
   # source .venv/bin/activate     # macOS / Linux
   pip install -r requirements.txt
   ```

   Developers and CI can use `pip install -e ".[dev]"` instead.

3. (Optional, legacy) Copy `.env.example` to `.env` and fill in credentials. Prefer the **Connections** tab instead - it stores credentials in encrypted per-profile storage. On first `python server.py` start, any `.env` credentials are imported once into the **default** profile's encrypted store and the plaintext `.env` file is deleted.

## Run the dashboard

**Recommended:** start the bundled dev server (serves the dashboard and lets you trigger fetchers from the UI):

```bash
python server.py
```

Windows shortcut: `.\scripts\start-server.ps1` (same venv launcher).

Then open **http://localhost:8765** in your browser.

**Read-only mode:** `python -m http.server 8080` if you only want to browse and run fetchers from the terminal. Personal edits fall back to browser `localStorage` instead of `data/personal.json`.

**Do not** open `index.html` directly - browsers block ES module loading from `file://`. Use one of the server options above.

## First steps after launch

1. Open the **Connections** tab and click **Connect** for each store you use. A headed browser window opens for cookie or OAuth sign-in. Credentials stay encrypted on your machine (OS keyring + AES-GCM fallback). See [Connecting stores](connecting-stores.md) for per-store steps.

2. After connecting, BAKLOG **auto-fetches** each store by default and opens the fetcher log. Fetcher chips in the **Fetcher health** row light up as each library lands. The ~90 second figure you may see in marketing copy was measured on an above-average Steam library (~2,000+ games); extremely large libraries take longer. Watch the fetcher log for progress.

3. Browse the **Dashboard**, **Library**, **Wishlist**, and **itch.io** tabs. See [Using the dashboard](using-the-dashboard.md).

### Steam-specific setup

Before your first Steam fetch:

1. Get a [Steam Web API key](https://steamcommunity.com/dev/apikey) (use `localhost` as the domain) - or let Connections grab it automatically.
2. Find your [SteamID64](https://steamid.io) (17-digit number starting with `7656119`) if connecting manually.
3. Set **Game details** to **Public** in Steam → Profile → Edit Profile → Privacy Settings.

## Optional: system tray

Keep BAKLOG running in the background with a tray icon - starts the same local server, opens your browser, and offers **Open**, **Restart**, and **Quit**:

```powershell
pip install pystray Pillow
.\.venv\Scripts\pythonw.exe tray_app.py
```

Or build a portable folder (includes its own `.venv` + tray `.bat` files):

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_installer.ps1
# then run dist\baklog\Start BAKLOG (tray).bat
```

**Start at login:** the tray menu can register login autostart (Windows registry / macOS LaunchAgent / Linux XDG). Frozen beta builds launch **BAKLOG Tray.exe** from the Start Menu or installer shortcut.

**Pro background refresh:** when the server process is alive (tray or `python server.py`), the paid tier scheduler refreshes stale stores without an open browser tab. Under Supabase auth, sign in once in the browser so the server caches your plan for headless refresh.

## Optional: production frontend build

Dev mode serves raw ES modules with `Cache-Control: no-store` (no `npm` required). For a smaller, cacheable production bundle:

```bash
npm ci
npm run build
$env:BAKLOG_SERVE_BUILT='1'; python server.py   # PowerShell
```

## Next steps

- [Connecting stores](connecting-stores.md) - per-store Connect steps and CLI fallbacks
- [Using the dashboard](using-the-dashboard.md) - tabs, filters, statuses
- [FAQ](faq.md) - free vs paid, invite-only access, no-games-yet paths
