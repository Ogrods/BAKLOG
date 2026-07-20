# Update Pipeline Overhaul Plan

## Issues Found (in-app update + version upgrade)

### 1. Banner needs padding above it

**Root cause:** The `.migration-banner` class (used by `#updateAvailableBanner`) has `margin-bottom: 0.9rem` but **no `margin-top`**. The banner sits flush against the dashboard content above it — there's no breathing room when it appears between the hero area and the game table.

**Fix:**

```css
#updateAvailableBanner:not(.hidden) {
  margin-top: 0.75rem; /* match #migrationBanner */
  margin-bottom: 0.75rem;
}
```

**File:** `app.css` — add a rule for `#updateAvailableBanner:not(.hidden)`

---

### 2. Modal window needs padding

**Root cause:** The update release notes modal (`#updateReleaseModal`) and install confirm modal (`#updateInstallConfirmModal`) use a generic modal template. The modal content area doesn't have adequate padding/margins — the release notes text, install button, and dismiss controls are crammed together.

**Fix:**

```css
.update-modal-content {
  max-height: 70vh;
  overflow-y: auto;
  padding: 1rem 1.25rem;
}
.update-modal-content p {
  margin-bottom: 0.75rem;
}
.update-modal-content .update-release-notes {
  margin-bottom: 1rem;
  line-height: 1.6;
}
```

**Files:** `app.css` + `js/update-check.js` `renderUpdateModalHtml()` — add a class to the modal content container.

---

### 3. "Server stopped unexpectedly" notification during update

**Root cause:** When the user clicks "Install & restart", the `apply_update.ps1` script kills the server and tray processes. The `_start_server_watchdog` in `tray_app.py` detects the dead child and notifies "BAKLOG server stopped — crashed again after a recent restart."

The tray watchdog doesn't know the difference between an expected shutdown (update) and an unexpected crash. After the update kills the old server, the watchdog runs, can't restart (because the zip is being extracted), and fires the crash notification.

**Fix:**

1. When the tray receives `POST /api/shutdown` from the update apply flow, set a flag (`_expected_shutdown = True`) that suppresses the watchdog notification for ~30 seconds.
2. The watchdog checks this flag before notifying.
3. After the flag period expires, normal crash detection resumes.

**Files:** `tray_app.py` — add `_expected_shutdown` flag to `ServerController`, modify `_start_server_watchdog` to skip notification when flag is set.

---

### 4. Add/Remove Programs not updated after zip update

**Root cause:** The `apply_update.ps1` script replaces the `_internal/` files in-place but does NOT update the Windows registry entries that were set by the Inno Setup installer (BAKLOG-Setup.exe). The "BAKLOG" entry in Add/Remove Programs still shows the old version.

The Inno Setup installer creates registry entries under `HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\BAKLOG_is1` with keys like `DisplayName`, `DisplayVersion`, `UninstallString`.

**Fix that's already implemented (but has quirks):**
The existing code in `update-check.js` has an `arp_version_mismatch` flag (`installHintsFromPayload`) that detects when ARP shows an old version. The `renderSetupArpFootnote()` function adds a note acknowledging the mismatch. This is a known limitation of zip-based updates vs installer-based updates.

**Remaining issues:**

- On some machines, the ARP entry briefly disappears during the file replacement (files removed before new ones extracted)
- The old uninstaller might still appear momentarily while the new registry values propagate

**Recommendation:**

- For the common case (zip-based install), document that ARP may lag behind and the app's own version check is authoritative
- After applying the update, run a background step that updates the registry `DisplayVersion` for the Inno Setup ARP entry if it exists
- Add a dedicated PowerShell function `Update-ArpRegistry` to `apply_update.ps1`

---

### 5. Banner still showing after install

**Root cause:** When the old server is shut down for update, the browser loses its connection. After the new server starts and the browser reconnects, the boot flow runs `checkForUpdates()` which calls `GET /api/update-check`.

The server sees the new version running and returns `updateAvailable = false`. But there's a race: if the browser reconnects before the new server is fully awake, the request fails, and the banner from the previous session (cached in localStorage or rendered before the refresh) might persist.

**Additionally:** The `read_dismissed_version()` check in `update_snooze.py` compares `dismissed_version` against `latest_version`. After upgrade, `latest_version` equals `current_version`, so `is_version_dismissed` returns `false` (correct — it's not a newer version being dismissed). But if the browser's `isUpdateBannerDismissed()` was called before the `/api/update-check` response was processed, it might have stale state.

**Fix:**

1. After a successful apply update, call `dismissUpdateForVersion(latest_version)` to clear the dismissed version in both server (`POST /api/update/snooze`) and localStorage.
2. On boot, if `current_version >= latest_version`, force-hide the banner and clear the dismissed state.
3. Add a post-apply cleanup step in `pollPostApplyOutcome()` that clears localStorage for the update banner.

**File:** `js/update-check.js` — modify `runApplyReadyUpdate()` and `pollPostApplyOutcome()`

---

### 6. No automated testing

**Current state:** The update pipeline (download → verify → apply → restart → post-apply check) has NO automated tests. All testing is manual.

**What needs tests:**

| Test Case                                  | What it verifies                                   |
| ------------------------------------------ | -------------------------------------------------- |
| `test_apply_script_backs_up_old_files`     | apply scripts create a backup before replacing     |
| `test_apply_script_rolls_back_on_failure`  | backup restored when new files fail SHA256         |
| `test_apply_script_cleans_old_backups`     | old backup directories are cleaned up              |
| `test_apply_result_written_on_success`     | `apply-result.json` with `ok: true` is written     |
| `test_apply_result_written_on_failure`     | `apply-result.json` with `ok: false` is written    |
| `test_version_in_registry_updated`         | ARP `DisplayVersion` matches new version           |
| `test_banner_hidden_after_upgrade`         | Banner doesn't show when current >= latest         |
| `test_banner_shown_when_update_available`  | Banner appears with correct version info           |
| `test_download_progress_reported`          | SSE progress events emitted during download        |
| `test_download_verified_sha256`            | Bad SHA256 rejects the download                    |
| `test_watchdog_suppressed_during_update`   | Tray doesn't notify during expected shutdown       |
| `test_apply_blocked_with_fetchers_running` | Apply refused when jobs are active                 |
| `test_apply_blocked_with_sign_in_active`   | Apply refused during browser sign-in               |
| `test_post_apply_poll_detects_success`     | Frontend detects `apply-result.json` after restart |
| `test_update_messages_render_correctly`    | Phase messages format correctly                    |

**Test categories:**

- **Unit tests** (Vitest + Python pytest) — dismiss logic, phase transitions, message formatting
- **Integration tests** (Python pytest) — `apply_update.ps1` with a mock zip, `update_manager.py` download/verify flow
- **Smoke test** (CI) — build the frozen bundle, run the update smoke test that verifies the whole pipeline end-to-end

**Files to create:**

- `tests/test_update_pipeline.py` — Python tests for `update_manager.py`, `update_ready_state.py`, `update_snooze.py`
- `tests/update-check.test.js` — Vitest tests for `update-check.js` frontend logic
- `scripts/test_apply_update.ps1` — PowerShell test for `apply_update.ps1` with mock zip
- `scripts/frozen_update_smoke.py` — CI smoke test for the frozen build update pipeline

---

## Implementation Order

### Phase 1: UI fixes (low risk, quick wins)

1. Add margin-top to `#updateAvailableBanner:not(.hidden)` in `app.css`
2. Add padding to update modal content area in `js/update-check.js` + `app.css`

### Phase 2: Notify suppression

3. Add `_expected_shutdown` flag to `tray_app.py` `ServerController`
4. Set flag when `POST /api/shutdown` received from update flow
5. Skip tray notification when flag is active (30s cooldown)

### Phase 3: Banner persistence fix

6. Clear dismissed version after successful apply in `pollPostApplyOutcome()`
7. Force-hide banner on boot when `current >= latest`
8. Clear localStorage update state after upgrade

### Phase 4: ARP registry fix

9. Add PowerShell function to `apply_update.ps1` that updates HKLM `DisplayVersion`
10. Run it as a final step after successful file replacement

### Phase 5: Testing

11. Write unit tests for dismiss logic, phase transitions
12. Write integration test for `apply_update.ps1` with mock zip
13. Write smoke test for frozen build update pipeline
14. Add CI job for update pipeline tests

---

## Issue 7: Email confirmation page 404

**Root cause:** `auth-gate.js` hardcodes the redirect URL as `https://baklog.app/auth/confirmed` (slash). But the landing file is `landing/auth-confirmed.html` (hyphen). Vercel's `cleanUrls: true` serves `/auth-confirmed` but 404s on `/auth/confirmed`.

Same issue affects password reset: `https://baklog.app/auth/reset` → should be `auth-reset`.

**Fix in `auth-gate.js` (lines 210, 216):**

```javascript
// Before:
return "https://baklog.app/auth/confirmed";
return "https://baklog.app/auth/reset";

// After:
return "https://baklog.app/auth-confirmed";
return "https://baklog.app/auth-reset";
```

**Supabase Admin Console:** Update **Authentication → URL Configuration → Redirect URLs** to use `auth-confirmed` and `auth-reset`.

**CSP fix in `landing/vercel.json`:** Add CSP override for `/auth-confirmed` matching the one at lines 69-78 for `/auth-reset` (both need `connect-src ... https://*.supabase.co`).
