# Troubleshooting

Common problems when connecting stores, running fetchers, or launching BAKLOG.

## Auth failures (exit code 4)

**Symptom:** Fetcher exits with code `4`; Connections card shows reconnect required.

**Fix:**

1. Open **Connections** and click **Reconnect** for that store.
2. Complete the headed browser sign-in flow again.
3. Re-run the fetcher from **Fetcher health** or the terminal.

Sessions expire on different schedules per store. Epic wishlist, Nintendo, and cookie-based stores tend to need refresh more often than API-key stores like Steam.

## Connect saved, fetch still fails

**Symptom:** Connections shows **Connected**, but the fetcher exits `4` or logs auth/capture errors.

**Cause:** Connect and fetch use different checks. Connect saves cookies or a Bearer token from the sign-in browser; fetch replays that session against the store API. A connect can succeed while the token is missing, stale, or rejected on the first library call.

**Fix by store:**

| Store | After Connect | If fetch still fails |
|-------|---------------|----------------------|
| **EA App** | Stay on **ea.com/sales/deals** until the window closes on its own | **Reconnect** (do not close early). Run `fetch_ea.py --headed --dump-debug` and check `cache/ea/fetch_debug.json` for token capture. |
| **GOG (web)** | Sign in at gog.com; wait for auto-close | Reconnect, or use `fetch_gog.py --source local` with Galaxy on Windows/macOS. |
| **Battle.net** | Open **account.battle.net/games** until your library list loads | Reconnect; on Windows Edge v127+ use Connect (not `--browser edge` jar read) or paste `BATTLENET_COOKIE` in `.env`. |
| **Humble** | Complete sign-in and any CAPTCHA on the library page | Reconnect with the library URL open. |
| **Epic wishlist** | Finish Epic login; use manual code paste if the redirect fails | Reconnect with **Fresh** if the profile is stuck. |
| **Xbox wishlist** | Complete Microsoft login in the headed window | Reconnect; advisory probe may show connected before wishlist fetch works. |

**General:** Use **Reconnect** (fresh profile clear when the store allows it), complete the full headed flow, then retry from Fetcher health.

## Suspicious empty result (exit code 2)

**Symptom:** Fetcher refuses to write an empty file; log mentions exit `2`.

**Cause:** BAKLOG preserves stale data when a fetch returns zero items unexpectedly (store outage, auth glitch, privacy setting blocking the library).

**Fix:**

1. Confirm store privacy settings allow the library to be read (Steam **Game details: Public**, PSN trophies **Anyone**, etc.).
2. Reconnect on Connections and retry.
3. If you truly have zero items, run with `--allow-empty` (advanced).

## GOG 403 Forbidden

**Symptom:** `fetch_gog.py` web source fails with 403.

**Fix:**

1. Reconnect GOG on the Connections page (refreshes the `gog-al` cookie).
2. On Windows/macOS with GOG Galaxy installed, run `python fetch_gog.py --source local` to read `galaxy-2.0.db` instead of the embed API.

## Windows: fetcher hangs or run queue wedges

**Symptom:** Fetcher chip spins forever; no log output; queue stuck.

**Cause:** Fetcher subprocess launched from the Microsoft Store `python.exe` stub instead of the project venv.

**Fix:** Always use `.venv\Scripts\python.exe server.py`. `server.py` auto-picks `.venv` when present.

## Chrome / Edge not found

**Symptom:** Connections sign-in fails to open a browser.

**Fix:**

1. Install Google Chrome or Microsoft Edge.
2. Set `BAKLOG_CHROME_PATH` to the full path of your browser executable.

## Battle.net cookie issues (Windows)

**Symptom:** `--browser edge` fails on Windows with Edge/Chrome v127+.

**Cause:** App-bound encryption can block the legacy fetch-time browser-jar read.

**Fix:** Use Connections → Connect (stored cookie avoids the jar read). Or paste `BATTLENET_COOKIE=` into `.env`, or use `--browser firefox`.

## Amazon on macOS / Linux

**Symptom:** Amazon launcher card shows **Unavailable**.

**Expected:** Launcher DB is Windows-only. Use **Amazon (Prime Gaming, web)** Connect + `python fetch_amazon.py --source web`.

## GOG Galaxy on Linux

**Symptom:** GOG Galaxy (local) unavailable.

**Expected:** No supported Linux Galaxy path. Use **GOG (web)** Connect instead.

## Count differs from the store

**Symptom:** BAKLOG shows fewer games than Steam/Epic/etc.

**Cause:** BAKLOG filters non-games (DLC skins, soundtracks, store apps, entitlement slugs) via the built-in blacklist. That is intentional - see [Using the dashboard](using-the-dashboard.md#blacklist-vs-hidden-list).

**Also:** Nintendo eShop fetch covers ~2 years of digital history only. Cartridge and older purchases need manual adds.

## Wishlist chip shows "missing"

**Symptom:** Fetcher health marks a wishlist file as missing.

**Expected:** Wishlist JSON files are optional per store until you run the matching script. See [Connecting stores](connecting-stores.md#wishlist-and-deal-prices).

## Stall watchdog messages

**Symptom:** Log shows `[server] no output for Ns - still running`.

**Expected:** Informational only when stdout is silent for 30s+. Large Steam libraries can take several minutes on first run. The process is not killed.

## Read-only mode: edits not saving

**Symptom:** Status changes disappear after reload.

**Cause:** Dashboard served via `python -m http.server` uses `localStorage` only.

**Fix:** Run `python server.py` instead. Or use **Export notes** / **Import notes** in the toolbar menu. A banner offers to migrate localStorage into `data/personal.json` on first server boot.

## Library gone after reinstall or update

**Symptom:** Connections and games missing after uninstalling, reinstalling, or updating the beta installer.

**Cause (older builds):** Library data lived in the same folder as `BAKLOG.exe`. Uninstall removed everything.

**Fix (current builds):** Data is in `%LOCALAPPDATA%\BAKLOG-Data` on Windows (separate from the app). If you still have that folder, reinstall BAKLOG and launch normally - first boot migrates any leftover data from the old install folder once. If you deleted `BAKLOG-Data`, restore from backup or a portable bundle export from Connections.

**Portable zip:** Add an empty `portable.txt` beside `BAKLOG.exe` only if you want all data in the unzip folder (thumb drives). Otherwise data goes to `BAKLOG-Data` automatically. If you used the default data folder first and later add `portable.txt`, the app will look beside the exe (which looks empty). Remove `portable.txt` to return to `BAKLOG-Data`, or copy your `BAKLOG-Data` folder beside the exe before enabling portable mode.

**Manual recovery:** If migration did not run or you still have files in the old install folder (`%LOCALAPPDATA%\BAKLOG`), copy these into `%LOCALAPPDATA%\BAKLOG-Data` (with BAKLOG closed): `profiles/`, `cache/`, `data/`, root `games_*.json`, `itad_prices.json`, `free_claims.json`, `.env`, and `license.json` if present. Launch BAKLOG again.

**Note:** Browser `localStorage` at `http://127.0.0.1:8765` can still hold default-profile UI prefs after a reinstall even when server files are gone. Use the migration banner to upload into `data/personal.json`, or clear site data if you want a truly fresh start.

## Connections lists many stores on a new profile

**Symptom:** A fresh profile shows many store cards (about 19) on the Connections tab.

**Expected:** BAKLOG lists every supported store you *can* connect. That is not the same as already connected. A new profile should show **0 stores connected** in the header until you click Connect. Local launcher sources (Amazon Games, GOG Galaxy, itch app) stay disabled on new profiles until you enable them on that profile.

## Bug reports vs fetcher failures

Dashboard JavaScript errors can be reported via the sticky toast or **Report a bug…** menu. Fetcher failures are separate - check **Fetcher health**, exit codes, and `profiles/<id>/cache/runs/*.jsonl`. See [Getting help](getting-help.md).

## Still stuck?

- [FAQ](faq.md)
- [Getting help](getting-help.md) - Discord, GitHub issues, email
- [Connecting stores](connecting-stores.md) - per-store privacy and fallback steps
