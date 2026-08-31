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

**Symptom:** Connections shows a browser warning, or sign-in fails to open a browser.

**Fix:**

1. Click **Connect** once while online - BAKLOG downloads a one-time browser (~150 MB) into its data folder when Chrome/Edge is missing.
2. Or install Google Chrome or Microsoft Edge.
3. Or set `BAKLOG_CHROME_PATH` to the full path of your browser executable.
4. Offline / air-gapped: install Chrome or Edge (or set `BAKLOG_CHROME_PATH`). `BAKLOG_NO_CHROMIUM_DOWNLOAD=1` disables the auto-download.

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

**Cause:** BAKLOG auto-hides non-games (DLC skins, soundtracks, store apps, entitlement slugs) as **library noise**. That is intentional - see [Using the dashboard](using-the-dashboard.md#library-noise-vs-hidden-list).

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

**Fix (current builds):** Data is in `%LOCALAPPDATA%\BAKLOG-Data` on Windows (separate from the app). Uninstalling via **BAKLOG-Setup** asks whether to keep that folder or remove everything (library, saved sign-ins, and login autostart). Choose **Keep my library** to reinstall later without re-connecting stores. Choose **Remove everything** for a clean slate (also clears the OS keyring master key used to decrypt Connections credentials).

If you still have `BAKLOG-Data`, reinstall BAKLOG and launch normally - first boot migrates any leftover data from the old install folder once. If you deleted `BAKLOG-Data` during a full wipe, restore from backup or re-connect stores in Connections.

**Portable zip:** Add an empty `portable.txt` beside `BAKLOG.exe` only if you want all data in the unzip folder (thumb drives). Otherwise data goes to `BAKLOG-Data` automatically. If you used the default data folder first and later add `portable.txt`, the app will look beside the exe (which looks empty). Remove `portable.txt` to return to `BAKLOG-Data`, or copy your `BAKLOG-Data` folder beside the exe before enabling portable mode.

**Manual recovery:** If migration did not run or you still have files in the old install folder (`%LOCALAPPDATA%\BAKLOG`), copy these into `%LOCALAPPDATA%\BAKLOG-Data` (with BAKLOG closed): `profiles/`, `cache/`, `data/`, root `games_*.json`, `itad_prices.json`, `free_claims.json`, `.env`, and `license.json` if present. Launch BAKLOG again.

**Note:** Browser `localStorage` at `http://127.0.0.1:8765` can still hold default-profile UI prefs after a reinstall even when server files are gone. Use the migration banner to upload into `data/personal.json`, or clear site data if you want a truly fresh start.

## Dev server vs frozen exe (same browser origin)

**Symptom:** The frozen beta shows the wrong library, old errors in bug reports, or UI prefs that match your git checkout - but `BAKLOG.exe` is supposed to use `%LOCALAPPDATA%\BAKLOG-Data`. A **Mixed sessions** chip means an older shared error log still has entries from both runtimes.

**Cause:** Dev (`python server.py`) and frozen (`BAKLOG.exe`) both serve on `http://127.0.0.1:8765`. The browser treats them as one site, so **UI prefs and auth tokens in localStorage are shared**. Server library files are **not** shared - they come from the active data directory. From 0.9.01 onward, the error history is stored per runtime (`baklog-error-log:dev` vs `:installed`) so bug bundles no longer mix the two. Older builds used a single `baklog-error-log` key.

**How to tell which server is running:** Open `http://127.0.0.1:8765/api/diagnostics` (or use **Report a bug**). Check `frozen` and `data_dir_path`:

| `frozen` | `data_dir_path` (typical) | Data source |
|----------|---------------------------|-------------|
| `false` | Your git repo folder | Dev checkout `profiles/` |
| `true` | `~/AppData/Local/BAKLOG-Data` | Frozen install data dir |

**Fix (library):** With BAKLOG closed, copy `profiles/` from your dev checkout into `%LOCALAPPDATA%\BAKLOG-Data`, or connect stores and refresh in the frozen app. Missing store files return an empty catalog (HTTP 200, zero games) - not your dev repo.

**Split dev from frozen (recommended on one PC):** Set `BAKLOG_DATA_DIR=%LOCALAPPDATA%\BAKLOG-Dev` and `PORT=8766` in `.env` before running `python server.py`. Dev library files stay in `BAKLOG-Dev`; the installed app keeps using `BAKLOG-Data` on port 8765. The header shows a **Dev server** chip when `python server.py` is active.

**Admin console vs installed library:** `BAKLOG_ADMIN=1` will not attach to the default installed data folder (`BAKLOG-Data`). Run admin against the repo (or `BAKLOG-Dev`). Only set `BAKLOG_ADMIN_ALLOW_INSTALLED=1` if you intentionally need admin on the installed library.

**Full clean of the installed library (maintainer / clean SoT):** Quit the tray, `BAKLOG.exe`, and any `server.py` on port 8765. Delete the entire `%LOCALAPPDATA%\BAKLOG-Data` folder. In Edge or Chrome, clear site data for `127.0.0.1` (and `:8766` if you used it). Launch the installed app once, create a new profile, and reconnect only the stores you want as the real library. Keep testing data under `BAKLOG-Dev` or the git checkout - do not copy testing dumps back into `BAKLOG-Data` unless intentional.

**Keyring caveat:** Connections encryption uses one OS keyring entry (`steam-backlog`) per Windows user. A full uninstall wipe removes it for both dev and frozen - you will need to sign in to stores again everywhere on that account.

**Fix (UI prefs / stale bug-report errors):** Edge or Chrome → site data for `127.0.0.1` → clear **localStorage**, or test the frozen build in an InPrivate window. Clearing site data does not delete `BAKLOG-Data`.

**Check migration:** `%LOCALAPPDATA%\BAKLOG-Data\.legacy_migration_done` lists what moved from the install folder on first frozen boot. If only `.env` moved, your library was never beside the exe - copy `profiles/` manually or refresh stores.

## Connections lists many stores on a new profile

**Symptom:** A fresh profile shows many store cards (about 19) on the Connections tab.

**Expected:** BAKLOG lists every supported store you *can* connect. That is not the same as already connected. A new profile should show **0 stores connected** in the header until you click Connect. Local launcher sources (Amazon Games, GOG Galaxy, itch app) stay disabled on new profiles until you enable them on that profile.

## Known issues (beta)

These are expected limits in the current open beta, not one-off bugs:

| Topic | What to expect |
|-------|----------------|
| **Windows-first** | The frozen installer and full Connect matrix are tested primarily on Windows 10/11. macOS/Linux work for most web stores; Amazon Games launcher and GOG Galaxy local are platform-limited (see [Supported platforms](../README.md#supported-platforms)). |
| **Dev vs installed on same PC** | `python server.py` and `BAKLOG.exe` share `http://127.0.0.1:8765` and browser site data. Use one at a time, or clear site data / use a private window when switching. Library files live in `%LOCALAPPDATA%\\BAKLOG-Data` for the installed app. |
| **Today's top deal ranking** | The wishlist hero picks the highest **deal score** (discount, historical low, rating), not always the lowest price. Hover the label for details. |
| **ITAD "no price data" warnings** | Some wishlist titles have no ITAD listing in your region (delisted, F2P, bundle-only, or title mismatch). The fetch still succeeds for the rest. |
| **Profile PIN** | PIN gates switching into a profile and destructive rename/delete on PIN-locked profiles. Library JSON on disk is not encrypted - treat PIN as a household lock, not encryption. |
| **Secrets store corrupt** | The encrypted credentials file for this profile cannot be read (wrong keyring entry, moved data, or a damaged file). Use **Reset store** on the banner, restore a backup on Connections, or reconnect each store. Archived copies are kept as `secrets.bin.corrupt-*` beside the old file. |
| **Cloud sync** | Signing in on a second PC does not copy your library yet. Copy `BAKLOG-Data` manually or wait for the planned Pro cloud mirror. |

## Unsigned beta builds (no code signing)

BAKLOG beta builds are **not code-signed** yet. That is normal for open beta - you are not doing anything wrong.

| Platform | What you may see | What to do |
|----------|------------------|------------|
| **Windows** | SmartScreen "Unknown publisher" on first launch or after manual download | **More info** → **Run anyway**. Only download from [GitHub Releases](https://github.com/Ogrods/BAKLOG/releases) or [baklog.app](https://baklog.app). |
| **Windows Setup + in-app updates** | Add/Remove Programs shows an older version than the app header | Expected: zip-based in-app updates replace files but do not refresh Inno's registry entry. Re-run **BAKLOG-Setup.exe** when you want Settings → Apps to match, or ignore if the in-app version is correct. **Copy diagnostics** shows `install_source`, `arp_version`, and `arp_version_mismatch`. |
| **macOS** | "App can't be opened" or quarantine after download/update | Right-click the app → **Open** once, or `xattr -cr /path/to/BAKLOG` in Terminal. Unzip to Applications or another stable folder, not directly from Downloads. |

We skip paid signing for now; future releases may add certificates. Verify SHA-256 sidecars on release assets when you want extra assurance.

## App updates (installed build)

**Symptom:** You want to know if a newer BAKLOG release is available.

**Behavior:** The installed (frozen) app can check GitHub once per launch for a newer release (toggle **Check for updates on startup** in the **⋮** menu; on by default). When an update exists, a banner appears under the header with **Update now** (when in-app apply is available), **What's new**, **Release page**, and **Remind me later** (snoozes that version until a newer one ships). If in-app apply is unavailable, the banner explains why (dev build, temp install, missing mac zip, etc.). The tray may also show a one-time notification on frozen builds. BAKLOG does **not** silently download updates in the background - you choose **Update now**, then **Install & restart**.

**Manual check:** Open the **⋮** menu and choose **Check for updates…** (works in dev and installed builds). When an update is available, a dialog shows release notes plus **Update now** / **Remind me later**. Progress and install steps use the same update banner (not the boot error strip). After download, an in-app **Install & restart** dialog replaces the browser confirm box. If you choose **Not yet**, a **Install & restart** banner stays until you apply or dismiss.

**Cancel:** While downloading, use **Cancel download** on the progress banner.

**Ready after restart:** If you downloaded an update but did not install yet, BAKLOG restores the **Install & restart** banner after a server or tray restart. Use **Discard download** to remove the verified package from disk.

**Apply failure:** If install fails mid-copy, the updater restores your previous build from a backup when possible and writes `%TEMP%\\BAKLOG-update\\apply-result.json`. The UI shows the error; if BAKLOG does not restart automatically, open **BAKLOG Tray** from the Start Menu (or run `BAKLOG Tray.exe`).

**In-app update vs Setup.exe:** Use in-app **Update now** for routine binary updates on Windows, macOS, and Linux frozen builds. Re-run **BAKLOG-Setup.exe** when Add/Remove Programs version drifts, shortcuts break, or `apply_update.ps1` / `apply_update.sh` is missing from the install folder.

**Zip-only uninstall:** Portable zip installs include **Uninstall BAKLOG.bat** beside the exes. Run it to clear login autostart and optionally wipe library data, then delete the install folder.

**Version:** Your current build version appears at the bottom of the **⋮** menu on installed builds.

**Platforms:** Windows uses `BAKLOG-win64.zip` + `apply_update.ps1`. macOS uses `BAKLOG-macos.zip` + `apply_update.sh`. Linux uses `BAKLOG-linux64.zip` + `apply_update.sh` (no tray relaunch - the Start script keeps the server in the terminal).

**Add/Remove Programs vs in-app version:** On Windows Setup installs, zip-based in-app updates replace app files but do not refresh the Inno uninstall registry version. Use **Copy diagnostics** or `GET /api/diagnostics` (`install_source`, `arp_version`, `arp_version_mismatch`, `trust_note`) to compare; re-run **BAKLOG-Setup.exe** when Settings → Apps should match the running build.

**Security:** Updates download only from the official `Ogrods/BAKLOG` GitHub release assets. The server verifies the published `.sha256` sidecar before apply is allowed. Apply is blocked while fetchers are running, a store sign-in window is open, or when BAKLOG is running from a temporary zip-extract folder.

**Note:** Your library data stays in `%LOCALAPPDATA%\\BAKLOG-Data` (macOS: `~/Library/Application Support/BAKLOG`) or your portable data folder — updates replace app binaries only.

## Bug reports vs fetcher failures

Dashboard JavaScript errors can be reported via the sticky toast or **Report a bug…** menu. Fetcher failures are separate - check **Fetcher health**, exit codes, and `profiles/<id>/cache/runs/*.jsonl`. See [Getting help](getting-help.md).

## Connect window closes immediately

**Symptom:** Battle.net, PSN, or another store Connect opens a browser window that closes within a few seconds.

**Fix:**

1. Confirm you are on **v0.9.00 or newer** (⋮ menu version, or `GET /api/diagnostics`).
2. Run BAKLOG from a permanent folder, not a temp zip extract (`running_from_temp: true` in diagnostics blocks in-app updates and can break profile writes).
3. Open your data folder (Settings or diagnostics `data_dir_path`) and check `connect-battlenet.log`, `connect-psn.log`, or `connect-cdp.log` after a failed attempt.
4. If the first Connect needs a one-time browser download, wait for the **Downloading BAKLOG browser** progress message before the window opens.
5. Use **Reconnect** and complete sign-in without closing the window early.

Include the relevant `connect-*.log` tail when reporting a bug (**Report a bug…** copies diagnostics automatically on recent builds).

## Still stuck?

- [FAQ](faq.md)
- [Getting help](getting-help.md) - Discord, GitHub issues, email
- [Connecting stores](connecting-stores.md) - per-store privacy and fallback steps
