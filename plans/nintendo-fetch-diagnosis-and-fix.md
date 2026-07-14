# Nintendo Fetch Failure — Diagnosis & Fix

## 1. What Failed

The most recent Nintendo library fetch ran at `2026-07-14T16:16:20Z` and **failed with exit code 4 (auth failure)**.

**Error:** `Nintendo session expired — open Connections and reconnect Nintendo.`

**Run log:** [`profiles/default/cache/runs/a82599df8fb4.jsonl`](../profiles/default/cache/runs/a82599df8fb4.jsonl)

## 2. Root Cause

| Factor                | Detail                                                                |
| --------------------- | --------------------------------------------------------------------- |
| Last successful fetch | `2026-06-25T21:00:44Z` (~19 days ago)                                 |
| Session lifetime      | `expiry_days=14` in [`auth/registry.py:339`](../auth/registry.py:339) |
| Expected              | Session exceeded its 14-day lifetime and expired                      |

The failure flow:

1. [`_nintendo_connected()`](../fetchers/fetch_nintendo.py:554) passes because the Chrome profile directory exists (has data from the old session).
2. [`NintendoClient.fetch_all_transactions()`](../clients/nintendo_client.py:172) picks the browser profile path since the dir exists.
3. Headless Chrome launches via [`launch_persistent_profile()`](../auth/cdp_browser.py:1516) with the saved profile and navigates to `https://ec.nintendo.com/my/transactions/`.
4. Nintendo returns the **sign-in page** because session cookies expired.
5. No Savanna GraphQL responses are captured → [`login_page_detected`](../clients/nintendo_client.py:381) is True.
6. [`NintendoAuthError`](../clients/nintendo_client.py:51) is raised, [`mark_invalid("nintendo")`](../auth/manager.py:350) is called, exit code 4.

## 3. Reconnect Button Issue

The user reports: **Reconnect button's browser window closes immediately**, but **Disconnect → Connect** works.

### Flow comparison

| Step | Reconnect (fresh=True)                                                | Disconnect → Connect (fresh=False)                                                         |
| ---- | --------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| 1    | Click Reconnect                                                       | Click Disconnect                                                                           |
| 2    | Server deletes profile + credentials blob                             | `disconnect()` deletes blob + profile dir                                                  |
| 3    | `launch_persistent_profile` creates fresh dir                         | Click Connect                                                                              |
| 4    | Chrome opens, `_extract_nintendo_inline` navigates to ec.nintendo.com | `start_browser_auth(fresh=False, state=disconnected)` → also calls `clear_browser_session` |
| 5    | User should sign in                                                   | Same launch flow as Reconnect                                                              |

Both paths ultimately call `clear_browser_session` + `launch_persistent_profile`, so the flows are structurally identical. The window-close-on-reconnect is likely either:

- A **race condition** where `clear_browser_session` kills a Chrome process that was still holding the profile, and before it fully terminates, the new Chrome instance fails to claim the profile (exit code 21) and retries
- A **Chrome version update** that changed how `--user-data-dir` handles newly-created directories
- An **anti-virus / Windows Defender** delay in deleting the old profile dir interfering with the new Chrome process

Since Disconnect → Connect works, the **practical fix** is to use that path.

## 4. Fix Applied

**Do the Disconnect → Connect workaround:**

1. Go to **Connections** → **Nintendo**
2. Click **Disconnect** (this clears the stale profile + credential blob)
3. Click **Connect**
4. Sign in with your Nintendo Account in the launched browser window
5. Let `ec.nintendo.com/my/transactions/` load fully
6. The window will close automatically and the session will be saved
7. Run the Nintendo library fetch again

## 5. Code Investigation (for Reconnect button bug)

If we want to fix the Reconnect button, here's what to investigate:

- [`auth/manager.py:702-705`](../auth/manager.py:702) — `clear_browser_session` runs on the **main thread** before the worker thread starts. The worker then calls `release_chromium_profile_lock` again in [`auth/runner.py:1651-1653`](../auth/runner.py:1651). This double-kill may race with Chrome's own teardown.
- [`auth/cdp_browser.py:1584-1627`](../auth/cdp_browser.py:1584) — `launch_persistent_profile` retries once if exit code 21 (profile in use), but the retry creates a **new subprocess** without killing the first one's orphans.
- The `clear_browser_session` → `launch_persistent_profile` gap on a fresh profile: [`_ensure_persistent_session_prefs`](../auth/cdp_browser.py:1459) writes a Preferences file before Chrome starts. If this write is partially complete when Chrome reads it, Chrome may silently exit.
