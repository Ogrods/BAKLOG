# Changelog

All notable changes to this project are documented here.

This project follows [Semantic Versioning](https://semver.org/): MAJOR for
breaking changes, MINOR for backwards-compatible features, PATCH for
backwards-compatible bug fixes. The single source of truth for the current
version is `pyproject.toml` (mirrored into `package.json` and the
`<meta name="baklog-version">` tag in `index.html` for bug-bundle metadata).

## Release discipline

1. Land changes under `[Unreleased]` as they happen — categorize under Added /
   Changed / Fixed / Removed.
2. When cutting a release: bump `pyproject.toml` + `package.json`, rename the
   `[Unreleased]` block to `[X.Y.Z] - YYYY-MM-DD`, open a fresh
   `[Unreleased]` heading above it.
3. Tag the commit: `git tag -a vX.Y.Z -m "BAKLOG vX.Y.Z"` then
   `git push origin vX.Y.Z`. The tag is the install-reproducibility contract;
   without it, "which version do you have?" is unanswerable for a second
   contributor.
4. **Before tagging:** run `.\scripts\release_preflight.ps1 -TagVersion vX.Y.Z`
   on Windows (includes pytest, Inno ISCC compile, optional full
   `build_windows.ps1`). CI `python-windows` must also compile `baklog.iss`.
5. **Gates (tagging only):** working tree must be clean and GitHub CI must be green on the release commit on `main` before tagging — not before merge. Never tag WIP or a red/pending CI commit.
6. **Broken public installer:** do not bump version for a bad build alone. Fix
   on `main`, keep `pyproject.toml` on the same version, run
   `.\scripts\replace_release_tag.ps1 -Version X.Y.Z -Force` to replace the tag
   and re-publish assets at the same version.

## [Unreleased]

### Changed

- `curated/free_claims.approved.json` and `curated/free_claims.auto.json` are gitignored (maintainer Claims ops only). Publish still commits `landing/free-claims.json` + `curated/free_claims.fallback.json`.
- Dropped stale machine-local editable `-e` path from `requirements-lock.txt`.

## [0.9.00] - 2026-08-06

### Added

- When Chrome/Edge is missing, Connections (and other CDP launches) download a pinned Chrome for Testing build once into the data-dir cache (`shared/chromium_runtime.py`, pin `shared/chromium_cft_pin.json`). System browsers and `BAKLOG_CHROME_PATH` still win; `BAKLOG_NO_CHROMIUM_DOWNLOAD=1` disables the fallback.

### Fixed

- Wishlist and dashboard ITAD deal UI stays gated until ITAD is connected (validated API key); hide price column, deal radar, picks Deals tab, and related deal chips when disconnected.
- Battle.net / PSN Connect quick-close diagnostics: PSN uses `run_connect_poll`, CDP launch logging (`connect-cdp.log` / `connect-psn.log`), tails in diagnostics and bug bundles, and troubleshooting for "Connect window closes immediately".
- Pruned stale free-claims approved ids so `audit_free_surface_data.py --fail-on high` stays green; rebuilt hosted/fallback feeds.
- `scripts/test-all.ps1` npm steps tolerate Vitest stderr deprecations under PowerShell `$ErrorActionPreference=Stop`.
- README / PRIVACY / CSRF docs aligned with shipped invite auth, Connections metrics toggle, and strict `X-BAKLOG-Local` mutating API.
- Responsive outside scan: `TABLE_PHONE_MQ` (+ phone chrome / A–Z dock) aligns with sheet landscape MQ so 844×390 uses library cards; `test:responsive` covers itch + outside overlays (notes/bug/update/kebab/profile/claimables/header nav/pro-compare) and `--auth-gate` mode.
- Responsive re-litigation: sheet modals get `overflow-y: auto` + flex `min-height: 0` under the landscape sheet MQ (notes/update no longer clip); phone library cards gain touch targets, hide dual cover EA ribbon, priority-hide COUCH when ONLINE coop is present, full-width sponsored house strip, and phone virtual-row height remeasure; `#summary` h-scroll aligns with sheet MQ and chip `min-height` uses `--touch-min`; wishlist/dash radar Tailwind `sm:grid-cols-3` → `lg:grid-cols-3` to match the 1024 CSS ladder.
- R5 responsive closeout: type tokens for ribbon/insight/score digits; tablet insight wrap; reduced-motion for error toast + pick/coop hover lifts; year-chart Chart.js duration gated; short-landscape chart/ribbon height trim; leftover app.css media (`640`/`760`/`767`/`768`/`520`/`420`) onto `1023.98`/`639.98`/`400`; fetcher `LOG_DESKTOP_MQ` `768`→`1024`.
- Responsive final UX audit: A–Z hit slop ≤1023.98; update/install `app-modal` sheets; sheet-mode MQ for phone landscape (`max-height: 480px` + `hover: none`) on modals/fetcher; auth gate bottom sheet + toast safe-area; `#picksGrid` holds 4 cols through tablet (6 at 1024); coop-versus 3-panel at 1024; scoreboards 1-col in sheet mode; Connections sticky Steam wrap + scrollIntoView; Pro compare `min-width` 22rem on phone; `test:responsive` adds 844×390 + Columns/Filters overlay smoke.
- p45 viewport leftovers: phone modals/dialogs/popovers as bottom sheets (safe-area + touch close); Connections sticky selected rail chip + pane body scroll + `conn-hint-row` on 1023.98 ladder; dash chart/ribbon heights on tablet/phone; retire leftover 900px library-count-host rule. Opt-in `npm run test:responsive` (`scripts/responsive-overflow-audit.mjs`) asserts no page overflow at 1024/768/390/360 × five views.
- Phone/tablet UX audit: dashboard picks stack at ≤1023.98 even with sponsored slot (`:has` 4-col override); wishlist/dash deal radar 1-col below 1024 (scoreboards no longer crush); filter pills + bulk bar horizontal scroll with 10px scrollbar pad; `#tableShell` A-Z gutter; phone sticky safe-area + back-to-top pin via bar bottom; Pro compare `overflow-x`; filter drawer safe-area + close touch; row-loading overlay centered above sticky; house banner breakpoints on 1023.98 / 639.98 ladder.
- Picks grid stays at least 2 columns on phone (`#picksGrid` CSS; committed Tailwind lacked `.grid-cols-2`, so the class alone collapsed to 1 col). Wider breakpoints still 4 / 6 / 8.
- Phone `#summary` chips hug content (not fixed equal width) with padded edges; the chip row scrolls inside `#summary` (`max-width: 100%`) so pills never widen the page.
- Phone LIBRARY sticky: compact rail back-to-top (no 44px touch inflate); header `#backToTopPhone` in the sticky strip (stand-in for thead `#backToTopCover`, which is hidden in card mode) shows while the table is pinned.
- Phone LIBRARY sticky bar: square top (no corner radius), opaque panel background, light bottom shadow so card chrome cannot peek through; A-Z rail / back-to-top raised and given a solid touch target so the arrow stays reachable.
- Phone library cards: keep store badges at fixed 16px (phone hug rule no longer sets `width: auto` on them, which collapsed Steam glyphs into a blank indent before coop pills); slightly stronger Steam badge outline on the default theme.
- Phone library cards: hide low-confidence `HLTB match:` hint to keep the three-line card compact (still available above phone / via HLTB override).
- Phone library cards: EA / hidden-gem sit immediately after the title (left, vertically centered on the title row) instead of trailing on the right.
- Phone library toolbar: Columns (|||) and kebab sit at the front of the Filters / Add game row (not above search); both icon buttons stay identical square size including touch targets.
- Phone library cards: keep three content lines (title + EA/gem beside title, meta chips, status under meta) - outer name flex stays row so badges are not a fourth line.
- Phone library cards: Status select stacks under the title/meta row (left-aligned in the content column) instead of floating end-aligned on the right.
- Phone library cards: coop/EA pills no longer stretch full width (scoped `.table-phone` name-cell flex to the direct child; meta chips wrap and hug; status select stays auto-width).
- Library Game column: revert fixed 14rem / max-width Game + sticky left cluster (they truncated titles and left empty mid-table gaps at full width); Game is fluid again (`width: 100%`); mid-width density + crush detection kept, with `min-width: 11.5rem` only under `#tableWrap.table-density`.
- Library mid-width table: denser auto-hide (through Steam/Played/HLTB if needed) when the Game title would crush.
- Library mid-width table: auto density hides Notes/Genres (then Last played/Released, then Price) so sticky thead survives (no `#tableWrap overflow-x:auto`); A–Z rail stays available below 1280px; phone sticky chrome bar; drill-to-row uses rect scroll on `table-phone` so spotlight/picks land correctly; notes mini-dialog when Notes column is hidden.
- Dashboard hero store strip snaps wrapped rows to balanced columns (e.g. 12 logos → 6+6, not 11+1).
- Dashboard stacked spotlight parks portrait/low-res covers about two-thirds across (right of center); `applySpotlightArtFit` stamps the offset so inline `object-position` no longer keeps them centered.
- Dashboard stacked spotlight caption hugs its text (`width: fit-content`) instead of stretching edge-to-edge.
- Dashboard mega-hero phone polish: stacked spotlight bleeds to the card top/sides so left/right corners match; phone pillars prefer a centered 2-over-1 row and wrap to a centered stack when too wide; insight pill hugs its text (`fit-content`, not full-bleed `display:block`).
- Dashboard mega-hero tagline on phone stacks one stat per line and hides the · separators.
- Header sheet: fetcher status circle is slightly smaller than the hamburger (1.75rem) and vertically centered (no upward translate).
- Dashboard picks on tablet/phone: Recently added (and versus) hug content height instead of keeping a desktop equal-row empty tail under a short list.
- Dashboard mega-hero on tablet/phone: spotlight art is contained to a stacked band (relative wrap + clip) so pillars/insight no longer cover the caption; pillars hug content width instead of full-bleed `1fr` cells; hero breakpoints migrate to the 1023.98 / 639.98 / 1024 ladder.
- Header sheet chrome: fetcher control sits left of the hamburger, sheet-mode fetcher pill matches icon-button size, and the beta pill keeps its full border (no upward translate under brand `overflow: hidden`).
- Phone/tablet usability: header brand/actions density, phone fullscreen fetcher sheet (reuse `#fetcherPopover`), connections stack on the tablet ladder (retire ad-hoc 720px), and dashboard strip containment so views stay usable without page-level horizontal scroll.
- Windows release build fully stops stray servers on port 8765 before frozen smoke (was `--dedupe`, which keeps a live listener and can fail the installer publish).
- In-app update modals (Install and restart / Update available) follow the active theme tokens instead of fixed slate/sky defaults; extend sky utility remaps (`bg-sky-500/700`, hover variants) to `--accent`.

### Changed

- Soft-sell Pro / Support BAKLOG copy across house creatives, Pro tab, tips, and landing FAQ; in-house Pro upgrade banners stay hidden (`HOUSE_PRO_BANNERS_ENABLED=false`) until the funnel review flips the flag.
- In-app updates stay explicit: boot check and tray notify only; no silent background download or apply-on-quit (Phase 6 silent update permanently deferred).
- Permanent Discord invite is `https://discord.gg/VFvxN5nCCB` (`shared/community.json`); linked from app kebab + footer socials, landing footer icons + Community column, README, and guide/getting-help.
- Fetcher health on phone opens as a fullscreen overlay sheet with sticky titled head; tablet keeps the anchored popover (dvh-capped).
- Main view tabs collapse to a hamburger sheet at tablet and below (replaces the phone horizontal scroll strip), and also when the inline header would wrap; sheet mode hides fullscreen and moves Report bug + profile into the overlay.
- CI: `workflow_dispatch` on the CI workflow; concurrency keyed per commit SHA; optional Playwright perf job is `continue-on-error` so manual tip checks can go green without shipping installers.

## [0.8.47] - 2026-08-02

### Changed

- Hide in-house Pro upgrade banners (dashboard/wishlist/library/itch stripes and spotlight house slides) behind `HOUSE_PRO_BANNERS_ENABLED` until the Pro funnel is ready for stranger beta. Paid placement paths are unchanged.
- README screenshot gallery uses Dashboard / Library / Wishlist / Connections shots from a generated fictional profile; hosted `#demo` copy no longer claims it mirrors the full app.
- Connections zero-state lead covers Epic, GOG, and Prime Gaming alongside Steam so free-start matches the landing narrative.
- Connected-but-empty dashboard hint points at fetcher chips instead of telling people to start a library fetch by hand (`autoFetchOnConnect` is the default).
- Hosted free-claims feed gets explicit CDN cache headers (`s-maxage=600`, stale-while-revalidate=3600).
- Refresh curated / landing free-claims feeds; dismiss null-end lingerers and prune stale null `ends_at` on carry-forward.

### Fixed

- Co-op tags chip no longer sticks at "N new" when Steam `appdetails` returns `success:false` (write `coop_online` / `coop_local` false; network exceptions still leave fields unset for retry).
- Free-claims publish no longer promotes mobile+EGS ITAD titles to unlinkable `epic_mobile` rows without `claim_urls` (keep `epic` + `claim_url`); fetch warning names dropped ids.
- Auto-hide exact title `fab-listing-live` as library noise like other non-game listings.
- Vitest house-creative suites opt into `setHouseProBannersForTest(true)` so CI stays green while production keeps house Pro banners off.

### Added

- Demo screenshot capture tooling (`scripts/generate-demo-profile.mjs`, `scripts/capture-screenshots.ps1` / `.mjs`) with a row-count contamination guard against real local libraries.
- `scripts/check_claims_feed_age.ps1` to warn when the free-claims feed is older than N days.

## [0.8.46] - 2026-08-01

### Fixed

- Dashboard no longer shows leftover Library/Wishlist/itch #summary chips after navigate (including cached dashboard returns).
- Library/Wishlist/itch status chips (e.g. Backlog) wrap in the same row as store/stat chips instead of a forced extra row.
- Connect URL/host checks use hostname allowlists (Battle.net/Epic) instead of substring/`endswith` host matching (CodeQL).
- Release gates rule: commit/push/merge first; clean tree + green CI only before tag.

## [0.8.45] - 2026-08-01

### Fixed

- Reviews and Co-op tags no longer hit the global 30-minute kill on large libraries (`maxRunSeconds: 0`, same as HLTB).
- Reviews/Tags flush catalog JSON mid-store so cancel or timeout keeps progress already written.
- Auto-enrich runs Reviews before Tags (Tags needs the appid map); empty-map Tags skips with exit 0 instead of sticky failed.
- Auto-enrich is true opt-in: missing/`undefined` pref no longer enables the checkbox or queues enrichers.
- Fetcher Cancel no longer sticks after short enrichers finish: ignore non-cancellable chip states, force-refresh idle `/api/runs` snaps, and reattach enrich-lane runs in `syncFromServer`.

### Changed

- Reviews storesearch delay 1.0s → 0.4s; appreviews throttle 1.5s → 0.75s (appdetails for Tags/Covers stays at 1.5s).

## [0.8.44] - 2026-07-31

### Fixed

- Red fetcher status pill / failed chip click always clears sticky failed state (including already-connected and non-auth failures), so the UI cannot stay bricked on a red pill; dual-source reconnect (`amazon_web` / `gog_galaxy` / `itch_local`) now clears the matching library chip too.
- Fetcher chips no longer spin forever after a missed SSE `done`: reconcile closes zombie EventSource streams when `/api/runs` history already finished, applies post-fetch reload, and stream-drop handling covers enrich lanes plus failed/cancelled outcomes.
- Connections "Cancel sign-in" control has spacing above the button under the connect log.

## [0.8.43] - 2026-07-31

### Fixed

- Epic Connect Cloudflare managed challenge on `/id/api/email/exists`: passively sniff the XHR body for `__cf_chl_tk`, open that URL in a background tab so CF's orchestrator can run (Epic was dumping challenge HTML into the form error as text, so the script never executed). Skip heavy STEALTH_INIT for Epic to reduce Bot Management noise; keep the system-browser OAuth escape hatch in the wait hint.

## [0.8.42] - 2026-07-31

### Fixed

- Epic Connect: revert 0.8.41 Epic fingerprint/DOM-polling/CF-classification changes that triggered Cloudflare managed challenges on `/id/api/email/exists` (restore `--disable-extensions`, stop per-tick `content()` scraping on the login page, page-mode-only CF detection). Epic library Reconnect now preserves the browser profile so `cf_clearance` survives retries; Disconnect still wipes clean.

## [0.8.41] - 2026-07-31

### Fixed

- Xbox / Nintendo wishlist Connect no longer flash-closes from orphaned fetcher Chrome: bounded profile close joins then force-releases holders; launch retry kills only pre-existing PIDs (not the new window); cancel API + UI when Connect stalls.
- Nintendo wishlist Connect no longer false-completes on an empty guest GraphQL wishlist; requires customer auth proof and logs polls to `connect-nintendo_wishlist.log`.
- Epic / Epic wishlist Connect: detect Cloudflare managed challenge HTML (`_cf_chl_opt` / Enable JavaScript and cookies), keep polling with a clear wait hint, and launch Epic Connect without `--disable-extensions` to reduce Bot Management flags.

## [0.8.40] - 2026-07-31

### Fixed

- Battle.net Connect no longer false-completes from a stale Chrome profile: sniffer matches `games-and-subs` only (not any `/api/`), in-page 401 ignores sniffer/external cookies and keeps the login window open, Connect always clears the Battle.net browser profile on start, and a post-connect `probe_browser_session` vetoes `mark_connected` when the saved cookie still gets 401.

## [0.8.39] - 2026-07-31

### Fixed

- Battle.net Connect hang on the Games page in frozen builds: `extract_battlenet_session` imported `battlenet_client` (and thus `browser_cookie3`) before sniffer/in-page success paths, so a missing frozen dependency returned `None` forever and never wrote `connect-battlenet.log`. Sniffer and in-page probe now run first; `browser_cookie3` is lazy-imported only inside `from_browser()`; Connect completes when the Games SPA proves the session; connect logging always tees under the data dir.

## [0.8.38] - 2026-07-31

### Fixed

- In-app Install & restart on Windows: root cause of the 0.8.36→0.8.37 apply failure. Launching the apply helper with `DETACHED_PROCESS` made `powershell.exe` exit immediately with rc=0 (no console host), so nothing was applied while the server still shut down and `applying.lock` blocked the tray watchdog. Drop `DETACHED_PROCESS`, use `CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP`, kill tray/server with a self-excluding process walk (never `taskkill /T` on ourselves), always write `apply-result.json` / clear the lock / relaunch the tray on failure, use .NET zip extraction, and require an `apply-started.json` handshake before shutting the server down. Apply progress goes to `%TEMP%\BAKLOG-update\apply.log`; lock TTL shortened to 120s with heartbeats.
- Battle.net Connect diagnostics: per-message rate-limited logging teed to `<data>/connect-battlenet.log` (visible under Tray launches), drop forbidden Origin/Referer from the in-page probe, broaden the network sniffer to any `account.battle.net/api` 200, and fall back to `Network.getCookies` with explicit urls when the CDP cookie dump is empty.
- Bug bundles / `/api/diagnostics`: include update phase, apply result, applying-lock age, and apply log tail so the next stuck-update report is conclusive.

## [0.8.37] - 2026-07-31

### Fixed

- Battle.net Connect: when the Games SPA already loads `games-and-subs` successfully, complete Connect from that network 200 (sniffer) instead of hanging on a failing external/in-page probe; re-select the live Games tab each poll; add Origin/Referer to the in-page probe; rate-limited stderr diagnostics for probe status/URL/cookies.

## [0.8.36] - 2026-07-31

### Fixed

- In-app Install & restart on Windows/macOS: stop the tray server watchdog from respawning BAKLOG while files are being replaced (`applying.lock`), launch the apply helper detached from the server process tree, and tree-kill tray/server before copying. Fixes the stuck "Installing update and restarting…" state where the UI never came back on a new build. (Re-released same version.)
- Battle.net Connect: verify the library session with an in-page `games-and-subs` fetch (real browser cookies + Origin) so arriving on the Games page completes Connect/Reconnect instead of hanging while an external probe keeps getting 401. URL-decode `XSRF-TOKEN` when probing from Python.
- In-app update: suppress and prune expected `/api/update/status` and `/api/update/apply-result` network errors across Install & restart (sessionStorage survives the relaunch; boot clears the flag). Stops sticky "Server unreachable" entries from dominating bug bundles after a successful update.
- Vitest forks pass `--no-experimental-webstorage` so Node 25 no longer shadows happy-dom `localStorage` (update-dismiss tests).

## [0.8.35] - 2026-07-28

### Fixed

- Headed Connect on Windows: Chrome/Edge launcher exit code 0 no longer aborts before CDP attaches (Battle.net and other browser sign-ins were closing immediately with "Browser exited immediately (code 0)"). Wait for `/json/version`, and on exit 0 with no CDP release the profile lock and retry once.
- Sticky **Install & restart** banner after a successful in-app update: ready packages that are already installed (or older) are discarded on boot, apply scripts clear the ready package after success, and a successful `apply-result` is acknowledged once with a short toast instead of re-showing the ready banner.
- Vitest sync-pair extractor accepts double-quoted `AD_LOCATIONS` in `admin/admin.js`; claims workspace stale-filter test matches the intentional default-All visibility of stale rows.
- Header brand badge shows Beta plus `vX.Y.Z` from `/api/config` (same source as the kebab version line).
- Tablet header wrap: order/`flex-basis` now target `.app-header-nav-wrap` so tabs drop to a full-width second row; phone nav fade uses `var(--bg)`.

## [0.8.34] - 2026-07-22

### Fixed

- Bump Pillow minimum version to `>=12.3.0` to resolve 7 Dependabot vulnerabilities (5 high, 2 moderate) in `requirements.txt` and `pyproject.toml`.
- Bump setuptools to `>=83.0.0` to resolve Dependabot alert (medium).
- `npm audit fix` to resolve brace-expansion (high) and js-yaml (high) transitive deps.
- Frozen build parity: `pyproject.toml` copied to bundle root for frozen version detection; bundle layout, data dir migration, fetcher dispatch, and import verification are all gated via `frozen_bundle_smoke.py`.
- Frozen `_import_smoke` subprocess console windows suppressed via `CREATE_NO_WINDOW`.
- Ruff lint warnings resolved in `scripts/` and `tools/` (E501, E701, F401, F841, I001).
- Lint errors in `server.py`, `dev_frozen_parity.py`, `server_internal_routes.py`.
- Updated curated free claims data (add/remove expired entries, update dismissed).

## [0.8.33] - 2026-07-14

### Fixed

- Steam storesearch/reviews CORS: proxy requests through local server using real browser User-Agent.
- Nintendo fetch auth failure: reconnect window was closing immediately after stale cookies; `abort_if_browser_closed` guards added to 6 connect extractors.
- Battle.net connect window closing immediately on stale cookies.
- Headless Chrome close blocks fetcher exit in `fetch_humble.py`, `fetch_humble_wishlist.py`, `fetch_nintendo.py`, `fetch_nintendo_wishlist.py`, `fetch_psn_wishlist.py`, `fetch_ubisoft.py` — switched to daemon threads.
- `fetch_amazon_web` lazy import prefix missing (`clients.` → `clients.amazon_web_client`).
- `fetch_free_claims` missing `enrich` lane in `/api/runs/cancel` validation.
- Sanitize blurb double-escape reverted in `claim-card.js` (entity decoding restored).
- Redact sensitive tokens in fetcher progress logging; 30 CodeQL alerts resolved.
- `insertAdjacentHTML` replaces `innerHTML` in update-check and trophy-popover.
- Mock pro-view.js in itch-tab-visibility test to prevent async leak after teardown.
- Test fixes surfaced by CI (two pre-existing failures, monkeypatch kwargs).

### Changed

- Dependabot dependency bumps (pip & npm) for security advisories.

## [0.8.32] - 2026-07-14

### Added

- Frozen bundle smoke tests: bundle layout, data dir migration, fetcher dispatch, and import verification.
- `pyproject.toml` copied to bundle root for frozen version detection.

### Fixed

- Frozen bundle root path serves app HTML instead of directory listing via `translate_path` resolving from `static_root()` for PyInstaller builds.
- CDP browser launch captures Chrome stderr on failure for diagnostics (Battlenet/Amazon_web connect).

## [0.8.30] - 2026-06-27

### Fixed

- Inno Setup install crash: `{app}` expanded in `InitializeWizard` before the install path exists (runtime error at line 82). Finish-page copy now fills on `CurPageChanged` when `{app}` is valid.

## [0.8.29] - 2026-06-27

### Fixed

- Inno Setup uninstall flow: replace invalid `CreateInputOptionPage(uwUninstall)` with MsgBox prompts (Inno has no uninstall wizard pages).

## [0.8.28] - 2026-06-27

### Fixed

- Inno Setup compile error on `CreateOutputMsgPage` (invalid extra parameters blocked v0.8.27 Windows release).

## [0.8.27] - 2026-06-27

### Added

- macOS release pipeline: `packaging/build_macos.sh`, CI `build-macos` job uploads `BAKLOG-macos.zip` + `.sha256` on tag.
- Unsigned-beta trust notes in diagnostics/update-check (`unsigned_beta`, `trust_note`) and guide docs (SmartScreen, Gatekeeper, ARP drift).
- `sign_in_active` on `/api/update-check` so the update banner hides **Update now** while a store sign-in window is open.
- In-app update recovery: apply scripts write `apply-result.json`, restore from backup on copy failure, and retain the newest `BAKLOG-backup-*` only.
- Ready-state persistence (`ready.json`) survives server/tray restart; **Discard download** clears verified packages from disk.
- `GET /api/update/apply-result`, `POST /api/update/discard-ready`; post-apply UI polling with tray restart recovery copy.
- Zip bundle ships **Uninstall BAKLOG.bat** for portable cleanup; Inno uninstall/finish copy is portable-aware when `portable.txt` exists.
- Apply blocked while a store sign-in window is open; update-check exposes `fetchers_in_flight` for proactive UI hints.

### Changed

- Personal doc load/save extracted to `shared/server_personal.py`; `server.py` line budget headroom restored.
- `apply_update.sh` no longer depends on system `python3` for path resolution.
- `js/fetcher/runner/index.js` added to module-size CI budget (2200 lines, ratchet down after splits).
- Public copy aligned to canonical **no telemetry by default** wording (README, SECURITY, Pro promo trust points, guide FAQ, landing trust section).
- **Run** / **RunManager** extracted from `server.py` into `shared/run_manager.py`; server line budget ratcheted to 3000.
- Connections left-rail grouping and status pills moved to `js/connections-rail.js`.
- Dev vs frozen footgun mitigated: document `PORT=8766` with separate `BAKLOG_DATA_DIR`; dev banner warns about shared localhost storage.
- Streaming download progress in `fetch_url_to_file`; tray notifies when a verified update is ready to install.
- Diagnostics and update-check expose `install_source`, `arp_version`, and `arp_version_mismatch` (Windows Setup vs zip apply visibility).
- Update install confirm footnote when Add/Remove Programs may lag behind in-app zip updates.
- Uninstall wizard choice: keep library data or remove everything (including `%LOCALAPPDATA%\BAKLOG-Data`, OS keyring master key, and login autostart).
- Header **Dev server** chip when `python server.py` is active; warns when persisted errors mix dev and installed sessions on shared localhost storage.
- `resolved_data_dir_for_uninstall()` so portable installs wipe co-located data beside `BAKLOG.exe`.
- `/api/config` `runtime_label` (`dev` / `installed` / `portable`) for UI runtime detection; `frozen` kept for compatibility.
- Tray menu **Open data folder** opens the active profile data directory in Explorer.
- Installer finish page shows library vs app paths; full uninstall nudges Connections **Export bundle** before wipe.
- `packaging/build_macos.sh` full PyInstaller build + CI attach on tag.

### Fixed

- Installer shortcuts and Add/Remove Programs icon: `BAKLOG.ico` now installed at `{app}\BAKLOG.ico` (was missing from the bundle root).
- Supersampled installer wizard images and multi-size `.ico` assets for smoother branding on HiDPI displays.
- Uninstall cleanup stops running BAKLOG processes before wiping data; tray uninstall flags require the frozen exe (dev `tray_app.py` cannot wipe install data).
- `/api/config` exposes `data_dir_path` for dev sessions (redacted), not only frozen builds.

## [0.8.26] - 2026-06-26

### Added

- Pro-gated **Run stale** button in Fetcher health (queues every stale store back-to-back).
- Guide **Known issues (beta)** section for stranger-wave expectations.

### Changed

- FAQ, README, landing, and in-app `PRO_PROMO`: queued bulk refresh is **live on Pro** (not coming soon).
- `EVENT_AUDIT.md`: EVT-03 agent-log blocks marked resolved.

### Fixed

- Profile **rename** requires PIN when the profile is PIN-locked (matches delete).
- Persisted **queue wait timeout** errors pruned after a healthy `/api/runs` sync.

## [0.8.25] - 2026-06-26

### Fixed

- Sign-in "Could not verify your session on the server" on frozen upgrades: install-dir auth `.env` now wins over stale `BAKLOG-Data` keys; data-dir auth file is overwritten on migration when bundled keys differ.
- ES256 Supabase access tokens: JWKS warmup at server boot, client retry with cache reset on transient HTTPS failures.
- Auth gate no longer fails sign-in after a successful session probe when comp-Pro refresh is best-effort only; longer probe backoff.
- Comp-Pro invitees on builds without `service_role`: server returns `plan=pro` without forcing `refreshSession` unless Supabase metadata was actually updated.

### Added

- `scripts/debug_auth_env.py` for local auth env / JWKS / JWT-secret alignment checks (no secrets printed).

## [0.8.24] - 2026-06-26

### Fixed

- Auth gate retries `/api/auth/session` briefly before showing a false "could not verify" error on first sign-in.

### Changed

- Installer branding uses the canonical rounded app icon (gradient mark, proper alpha in `.ico`); desktop and Start Menu shortcuts use `BAKLOG.ico`; tray and frozen exes embed the same icon.

## [0.8.23] - 2026-06-26

### Fixed

- Frozen upgrades: sync bundled auth `.env` from the install folder into `BAKLOG-Data` when auth keys are missing (fixes sign-in "Could not verify your session on the server" after reinstall).
- PyInstaller builds set certifi CA bundle for Supabase JWKS verification.

## [0.8.22] - 2026-06-26

### Added

- Hosted auth pages on baklog.app (`/auth/confirmed`, `/auth/reset`) plus `api/auth-config` for password reset.
- Resend confirmation email button on the auth gate when sign-in fails with unconfirmed email.
- Supabase email template files under `landing/supabase-email-templates/`.
- Pre-release `release_smoke` pytest marker: live Steam store contract + batch client regression (`tests/test_release_smoke.py`); runs in `release.yml` and `test-all.ps1 -Full`.

### Changed

- Sign-up and password-reset redirects default to baklog.app (confirm from phone or any device).
- Tagged releases build and ship `BAKLOG-Setup.exe` (Inno Setup on CI) alongside the portable zip.
- Windows installer branding: BAKLOG icon, wizard images, and updated welcome copy (`packaging/generate_installer_assets.py`).

### Fixed

- Steam library fetch: store `/api/appdetails` returns HTTP 400 for comma-separated appids; `get_app_details_batch` now fetches one appid per request.
- Inno Setup script: `{localappdata}` constant for `BAKLOG-Data` path (was invalid `{userlocalappdata}`).

## [0.8.21] - 2026-06-25

### Added

- Custom ordered lists in Picks (up to three user-named library tabs, drag reorder, bulk Add to list).
- Library noise transparency: **Filtered N non-games** summary chip, noise-only hidden panel view, **Not a game?** false-positive report.
- Automated tests for noise summary chip, chip-to-panel wiring, custom-lists integration, and fetcher noise-tag migrations.

### Changed

- Fetchers tag more non-game rows with `noise` instead of dropping them (GOG non-game `mediaType`, Nintendo vouchers/subs, Epic addon-only catalog, itch non-videogame classifications).
- Guide: document the Filtered non-games chip under library noise.

### Fixed

- Deal-hero card omits HLTB stat when main story hours are zero or missing.
- Nintendo `edition_title_join_key` for receipt-to-catalog title joins.
- Fetcher library-noise rule consolidation (`shared/library_noise.py` sync pair).

## [0.8.20] - 2026-06-25

### Added

- Post-build frozen bundle smoke gate (`scripts/frozen_bundle_smoke.py`): layout,
  bundled auth `.env`, data-dir migration, `/api/config`, and fetcher dispatch.
- Release workflow fail-fast check for `BAKLOG_SUPABASE_URL` / `BAKLOG_SUPABASE_ANON_KEY`
  before PyInstaller runs.
- Maintainer `provision_pro_user` CLI for comp-Pro beta ops.
- Header full-screen toggle (TV icon) between fetcher log and profile menu.
- `scripts/release_preflight.ps1` local gate before tagging (version sync, GH secrets, test-all -Full, optional frozen build).

### Changed

- Affiliate disclosures: Green Man Gaming (Impact) enrollment noted in
  `landing/index.html`, `PRIVACY.md`, and `js/affiliate.js` (sponsor creatives
  still pending).
- Release workflow runs frontend build + dist-integrity + bundle-size checks before PyInstaller.
- `packaging/build_windows.ps1` logs whether auth env vars are set (no values) before writing bundled `.env`.

## [0.8.19] - 2026-06-25

### Added

- Self-service Supabase signup plus forgot/reset password on the auth gate.
- Comp-Pro on login for invitee emails listed in `packaging/pro_invitees.txt`
  (requires `SUPABASE_SERVICE_ROLE_KEY` on the server that handles sign-in).

### Changed

- Frozen installs store library data under `%LOCALAPPDATA%\BAKLOG-Data` on
  Windows (resumable migration from a co-located install; `portable.txt` keeps
  single-folder mode). `BAKLOG_DATA_DIR` override still migrates from the legacy
  install dir on first boot.
- Shared connect loop and smoother headed sign-in for browser-backed stores.
- Dependabot dependency bumps (GitHub Actions, pip, npm) and server helper
  extractions (`shared/server_auth_session.py`, `shared/server_epic_oauth.py`,
  and related modules).

### Fixed

- EA Connect: GraphQL hook pipeline, profile isolation during connect, and
  `initial_url` on `launch_persistent_profile` (regression from the EA connect
  merge).
- Library count combat-text: sequential `+1` popups, linear hero roll,
  tick-synced popups on small acquisition deltas, and mega-hero handoff when
  `fireLibraryCountFlash` owns the burst.
- Profile dismiss/switch isolation and related localStorage scoping.
- CI stability after dependency merges (Vitest, ruff, server line budget,
  Linux pytest flakes).

## [0.8.18] - 2026-06-15

### Fixed

- Legacy `.env` migration now strips only the imported store-credential lines and
  preserves operational config (`BAKLOG_SUPABASE_*`, `BAKLOG_ADMIN`, Polar org id,
  etc.), deleting `.env` only when nothing but credentials and comments remain.
  Previously the whole file was deleted after import, which could wipe a
  self-hoster's settings.

### Added

- `.github/CODEOWNERS` and an opt-in `.pre-commit-config.yaml` (ruff lint plus
  basic file hooks).

### Changed

- Release workflow now runs the Python and JS test suites before building, so a
  tag can never publish from a commit whose tests fail, and attaches a signed
  SPDX SBOM (in addition to the existing build-provenance attestation).

## [0.8.17] - 2026-06-15

### Added

- Tag-triggered immutable release workflow (`.github/workflows/release.yml`):
  pushing a `vX.Y.Z` tag builds the Windows bundle on a clean runner, verifies
  the tag matches `pyproject.toml`, attaches a SHA-256 and a signed
  build-provenance attestation, and publishes the GitHub Release.
- Contributor scaffolding: `CONTRIBUTING.md`, pull-request and issue templates,
  weekly Dependabot (pip / npm / github-actions), and an `.editorconfig`.

### Changed

- Reorganized the root Python modules into `clients/`, `fetchers/`, and
  `enrichers/` packages with package-qualified imports. No behavior change;
  verified end to end against a frozen build (all 27 fetchers dispatch).
- Refreshed the free-claims feeds and pruned expired approved giveaways.

### Security

- Legacy `.env` credentials are now deleted after import instead of being
  renamed to `.env.imported`, so no plaintext secrets are left on disk.

## [0.8.15] - 2026-06-14

### Added

- **Report bug** button in the header (next to Pro) for one-tap bug-bundle capture.
- Beta blind-spot hardening: warn when the frozen exe runs from a temp/zip-extract
  folder (`running_from_temp` in `/api/config` + boot banner); self-heal stale
  Windows login-autostart registry entries on boot; opt-in `GET /api/update-check`
  and kebab **Check for updates**; scrubbed `GET /api/diagnostics` + kebab **Copy
  diagnostics**; `STEAM_PRIVATE_PROFILE_HINT` when Steam returns 0 games with
  valid credentials (private Game details).

### Changed

- **Fetcher auto-refresh defaults off** — ITAD auto-refresh, claims auto-refresh, and
  auto-enrich new games now ship disabled in `js/prefs.js`; opt in from the fetcher
  health panel.
- **Marketing live-state reconciliation (Jun 2026)** — landing, deck, one-pagers,
  content-kit, and README aligned to code-grounded canonical copy: paid tier live
  ($5/mo · $50/yr via Polar); 300+ stats canonical; cloud sync, queued bulk
  refresh, deal/watchlist alerts, and premium palettes marked coming; credit-pack
  story removed; em dashes stripped from one-pagers and landing.
- Marketing: open-source (MIT) claim threaded through landing page (hero, trust,
  FAQ, footer, structured data) and README; canonical GitHub repo URL added to
  `shared/community.json`.
- **Audit remediation (2026-06-09)** — static path guards moved to
  `shared/server_static.py` (decode + casefold + realpath containment); app shell
  `/` resolves `index.html` on Python 3.13+; cover URLs routed through escaped
  `safeCoverAttrUrl` / `safeCoverCssUrl`; secrets master-key fallback hardened
  (DPAPI/keychain, narrow except); Amazon raw-claims scrub third-party codes;
  CDP `--remote-allow-origins` scoped; Epic OAuth callback always requires
  server-minted state; landing `report.js` / `subscribe.js` rate limits + body
  caps; API body limits and log redaction gaps closed; `findGameByKey` indexed;
  localStorage quota guards; pre-push leak-scan hook; README/PRIVACY hosted-surface
  copy reconciled.

### Fixed

- **Dashboard marquee stuck at two chips after hard reload** — boot’s second
  `scheduleDashboardRender` could cache-hit a sparse marquee built under stale
  `metricsDisabled` and re-poison metric keys from filtered chips. Mega-artifact
  fingerprint now includes `metricsDisabled`, cache stores pre-filter
  `marqueeMetricKeys`, and a corruption guard heals implausibly bloated disabled
  sets (`js/dashboard.js`, `js/metrics-rendered.js`).
- **App shell 404 with Supabase auth** — `GET /` returned 404 because Python
  3.13 `translate_path` no longer maps directory requests to `index.html`.
- **Flaky `cancel-in-flight` queue test** — suppressed run ids persisted in
  `sessionStorage` leaked across tests (`vi.resetModules()` re-hydrated them at
  module init), so `runBlocksQueueSlot()` could drop a still-active run and flake
  `isQueueFull()`. Tests now clear storage in `beforeEach`.
- **Vitest unhandled rejection** — `cancel-in-flight.test.js` now stubs
  `EventSource` for fetcher SSE subscribe paths.

## [0.8.0-beta.1] - 2026-06-11

First private Windows beta build candidate (`packaging/build_windows.ps1`).

### Fixed

- **Update-check repo slug** — `GET /api/update-check` now queries
  `Ogrods/BAKLOG` releases (was `Ogrods/steam-backlog`, which always 404'd).
  URL is derived from `shared/community.json` `github_repo`.
- **Pre-ship audit quick-wins** — mutating API routes normalize through
  `_api_path()`; `/api/diagnostics` refresh log tail redacted; per-request
  `load_dotenv` removed from `_handle_fetchers`; dead `PERSONAL_DIR`/`PERSONAL_FILE`
  globals removed.
- **`fetch_itad.py` auth contract** — invalid/revoked key mid-run →
  `mark_invalid("itad")` + exit 4 (not traceback + exit 1).
- **Epic Connections status** — checks `epic_session` secrets blob before
  `session.json` heuristic.
- **JS hygiene** — unused imports trimmed; null guards on kebab menu and
  bootstrap prefs DOM writes.
- **Tests** — `fetch_nintendo_wishlist.py` in auth-exit regression list;
  `library-universe` tests seed `itch_local` connected for itch gating.

## [0.7.0] - 2026-06-08

### Added

- **Beta ship hardening** — PyInstaller `BAKLOG.exe` is the recommended tester bundle: auto-opens the browser on start, pauses the console on fatal errors (frozen builds), ships `BETA-README.txt` + `Start BAKLOG.bat`, and emits a SHA-256 checksum for the release zip (`packaging/build_windows.ps1`).
- **`GET /api/config` runtime fields** — `version`, `frozen`, and `chromium_available` for bug bundles and Connections preflight.
- **Packaging drift test** — `tests/test_packaging_manifest.py` asserts every `fetchers/manifest.json` script appears in `packaging/baklog.spec` `hiddenimports`.

### Changed

- **Portable build script** — `scripts/build_installer.ps1` prefers `git archive` (tracked files only) and fails the build if `secrets.bin`, CDP session profiles, or `games_*.json` leak into output.
- **Connections preflight** — amber banner when Chrome/Edge is missing (`connBrowserWarn` + `chromium_available` from config).
- **Empty-library boot banner** — points testers to Connections instead of `fetch_games.py`.

### Fixed

- **PyInstaller fetcher imports** — `fetch_free_claims` and all five enrichers added to `hiddenimports` (auto-enrich no longer crashes frozen builds).
- **Private tracker leak** — `tracker.html` removed from `baklog.spec` and denied by `server.py` static gate.
- **Debug agent-log POSTs** — removed leftover `#region agent log` blocks from `js/fetcher-health.js` and `js/claimable.js`.
- **Frozen port reclaim** — `pid_is_python_server` now also matches a stuck `BAKLOG.exe` (not just `python`), so a second launch can reclaim an orphaned frozen instance on port 8765 (`shared/dev_server_pids.py`).
- **Read-only data dir** — `server.py` fails fast with a clear "move to a writable location / set `BAKLOG_DATA_DIR`" message instead of silent write failures when a frozen build runs from a read-only folder.
- **`fetch_games` test** — `fetch_games.py` imports `sys` so `test_fetch_games_network.py` can patch `argv` (was `AttributeError: module 'fetch_games' has no attribute 'sys'`).

### Changed

- **Deep sync gated behind paid tier** — removed the unapproved daily free-allowance/credits meter (`js/achievement-meter.js` deleted). The trophy popover **Deep sync** button (PSN/Xbox full achievement/trophy re-pull) now renders only when `isPro()` is true; free tier keeps cached completion % only. Landing FAQ, tier-compare table, and README aligned to "cached % only" vs "full re-pull".
- **Claim source badge reads "ITAD"** — the per-claim "via …" attribution badge for IsThereAnyDeal-sourced giveaways now shows the short **ITAD** label (`CLAIM_SOURCE_META.itad` in `js/claimable.js`), matching the abbreviation used elsewhere in the UI. The hover tooltip and source link are unchanged.
- **Auto-refresh stores older than 24h now defaults on** — the Connections pref `autoFetchStale24h` ships enabled (`js/prefs.js`); new installs quietly refresh one stale store per ~30 min while the app is open, and the toggle in `index.html` is checked by default. Still user-disablable. README and landing copy updated to match.
- **Bulk "Run stale" button hidden** — the fetcher-health bulk queue sweep conflicts with the no-queue free-tier philosophy, so the button is no longer rendered (`staleButtonHtml` is empty in `js/fetcher-health.js`). `runAllStale()` and its click handler stay intact (dormant) for a one-line re-enable. On-demand bulk refresh is repositioned as a planned paid-tier perk; landing page gains a "Paid tier (planned)" premium box and the FAQ lists the run-stale queue sweep. Single-store 24h auto-refresh stays free.

### Fixed

- **Agent debug instrumentation purged** — removed leftover Cursor debug-mode `fetch()` POSTs to dead local ingest ports (`127.0.0.1:7320`, `:7802`) and the `debug-3a594f.log` writer in `server.py` from `js/claimable.js`, `js/sponsored-deals.js`, `js/dashboard.js`, `js/dashboard-charts.js`, `js/dashboard-cards.js`, and `js/library-load.js`. These were firing on normal dashboard loads and spamming `ERR_CONNECTION_REFUSED`.
- **`/api/runs/cancel` profile scope** — when Supabase auth is on, cancel-all / force-reset now scopes to the signed-in user's profile via `_bind_request_user()` instead of the local `profiles/index.json` active id (which broke per-user isolation tests and could cancel another account's runs).
- **Pytest env isolation** — `tests/conftest.py` clears `BAKLOG_LOCAL_PROFILES`, `BAKLOG_PROFILE`, and `BAKLOG_PLAN` from dev `.env` so CI/local runs match the default-profile assumptions in auth and enricher tests.

### Added

- **Plan / entitlement (moat-preserving ads)** — `shared/entitlement.py` resolves `free` vs `pro` (env override → signed Supabase JWT claim → local `license.json` honor-system file). `GET /api/config` exposes `plan`; `js/auth-gate.js` `isPro()` gates the sponsored deal slot (`getEligibleSponsoredDeal` returns null for pro). Paid tier removes ads without reversing the local-first privacy moat; hosted feed coupling + Ed25519 offline license deferred.

### Fixed

- **Blacklist: Epic entitlement slugs** — internal Epic slugs that leak in as titles (single token, no spaces, joined by an underscore — e.g. `Fortnite_StWContent`, `Fortnite_Studio`) are dropped by the hardcoded _blacklist_ (`isJunkEntry` in `js/game-core.js`, mirrored by `_is_entitlement_slug` in `fetch_epic.py`). Real titles use spaces (`Aerial_Knight's Never Yield`) so they are unaffected. Terminology note: the **blacklist** is hardcoded non-games that are never shown; the **hidden list** is user-editable games restorable from the Hidden games panel (seeded by `js/hidden-defaults.js`). New filtering should pick a bucket — see the README "Blacklist vs hidden list" table.
- **`.gitignore` store JSON globs** — `games_*.json` and `games_wishlist_*.json` replace per-file enumeration so Humble, EA, and Nintendo-wishlist catalog files (and future stores) cannot be committed accidentally.
- **`gameId()` EA drift** — `js/game-core.js` now includes the `ea_id` fallback (aligned with `normalizeGame()` and the table-query worker).
- **Landing CSP** — waitlist handler moved to `landing/main.js`; JSON-LD externalized to `landing/structured-data.json`; Google Fonts load via `id="google-fonts"` (no inline script). Demo spotlight nav uses sibling buttons (no nested interactive controls).
- **Subscribe email sanitization** — `landing/api/subscribe.js` strips control characters before Resend `reply_to`.
- **`/api/runs/cancel?force=1` routing** — `server.py` matches the path without query string so force-reset works when auth is on.

### Changed

- **Marketing copy consistency** — landing page, content kit, investor deck, one-pager, README, and waitlist email aligned to shipped auto-fetch behavior (on-connect default on; 24h stale refresh default off; no background/cloud sync claims). Magic-moment numbers standardized to 0 → 2,000+ in ~90 seconds; fetcher panel described as 25 chips (12+8 stores + ITAD + enrichers).
- **Connections status pills (3 states)** — scrapped the client-side "Connecting…" animation. Pills now show only **Connected**, **Unverified**, or **Not connected** from server truth (`displayStatus()`); `expired` still drives Reconnect chip/banner but displays as "Not connected" on the card. Post-connect speed uses Epic callback `BroadcastChannel` + a 30s time-boxed fast poll (no fake in-flight state).

### Fixed

- **Virtual table scroll white flashes** — dark `html` / `#tableShell` / `.games-table` backgrounds so `contain: paint` repaints never expose the white canvas; virtual overscan raised from 10 to 20 rows to reduce blank gaps on fast flicks.
- **Connections rail crash** — fixed leftover `eff` reference in `buildRailItemHtml` after the three-state status refactor (`ReferenceError: eff is not defined` broke the Connections tab).
- **Connections status refresh errors** — failed `/api/auth/status` no longer wipes the provider list when cached data exists; messages distinguish sign-in required (401), server errors, and offline instead of always blaming `server.py`.
- **Audit hardening** — deduplicated Supabase bearer→profile binding (`_bind_request_user`); `cancel_all` / `force_reset` scoped to the signed-in profile when auth is on; [SECURITY.md](SECURITY.md) documents optional invite-only login.

### Added

- **Epic browser sign-in (redirect OAuth)** — `POST /api/auth/epic/oauth-url` returns an Epic login URL whose `redirectUrl` points back to the local `/oauth/epic/callback` with a single-use, profile-bound `state`; the callback exchanges the `authorizationCode` and connects Epic to the signed-in profile. Available as "Sign in with your browser instead" in the Epic Connections fallback drawer; the Playwright auto-capture flow remains the default.
- **Supabase invite-only sign-in** — optional account gate: full-screen login overlay, `GET /api/config`, JWT verification on `/api/*`, and one isolated `profiles/<user-id>/` data tree per invited user. Configure `BAKLOG_SUPABASE_URL` and `BAKLOG_SUPABASE_ANON_KEY` in `.env`. Local dev without Supabase: `BAKLOG_AUTH_DISABLED=1` in `.env`.
- **GOG Galaxy + itch butler local scan** — dual-source library fetchers mirror the Amazon launcher/web pattern. `gog_galaxy_client.py` reads `galaxy-2.0.db`; `itch_local_client.py` reads `butler.db`. `fetch_gog.py` / `fetch_itch.py` use `--source auto` (local first), union-merge per-source slices with drift guards, and shared filtering via `gog_filters.py` / `itch_game.py`. Fetcher-health treats a connected local sibling (`gog_galaxy`, `itch_local`) as satisfying GOG/itch credentials so reconnect chips and missing-key warnings do not fire when only the launcher DB is present.
- **Runaway-process / test-hang guard** — the dev server caps every fetcher run at `MAX_RUN_SECONDS` (override via `BAKLOG_MAX_RUN_SECONDS`) and kills past the cap with a clear log line; `popen_fetcher` launches under a Windows job object so the whole child tree dies with the parent; `RunManager.join_threads()` drains workers on shutdown (`shared/subprocess_guard.py`). Test side: `pytest-timeout` (60s, faulthandler 70s) plus a `tests/conftest.py` thread/subprocess leak detector that dumps stacks instead of letting CI hang.
- **`python -m auth expire <provider>`** — dev/test helper that marks a Connections provider Session expired (`mark_invalid`) so the dashboard Reconnect chip is reproducible without waiting for a real auth failure. `python -m auth expire --list` prints valid provider keys.
- **Library watch** — after a Steam purchase, BAKLOG can watch for a title to appear in `games_steam.json` (Steam’s API often lags the client). `js/library-watch.js` arms watches in profile-scoped `localStorage`, shows a waiting banner with “Run Steam fetch”, polls every 5 minutes while the tab is open, and alerts when the game lands (in-app banner + optional desktop notification). Pico Park is armed by default on boot.
- **Steam Store API retry** — `steam_client.py` retries transient connection errors and HTTP 429/5xx on app-details and review calls with backoff.
- **Epic wishlist via saved browser profile** — dropped `EPIC_STORE_COOKIE` Python replay (Cloudflare-bound). `fetch_epic_wishlist.py` reuses `cache/auth/profiles/epic_wishlist` headlessly, captures storefront GraphQL, writes `games_wishlist_epic.json`. Auth connect returns a profile marker; `--dump` saves `cache/epic/wishlist_dump.*`.
- **Humble in Steam enrichers** — `enrich_steam_reviews.py` and `enrich_cross_store_images.py` now process `games_humble.json`; reviews enricher uses `humble_steam_app_id` when present.
- **Humble Bundle library + wishlist** — new `humble` Connections provider (CDP browser profile at `cache/auth/profiles/humble`, one login for both fetchers). `fetch_humble.py` walks `/api/v1/user/order` + per-order detail, games-only by default (`--include-nongames` escape hatch), writes `games_humble.json`. `fetch_humble_wishlist.py` loads `humblebundle.com/store/wishlist`, parses `__NEXT_DATA__` + captured wishlist XHR, writes `games_wishlist_humble.json`. Manifest keys `humble` + `wishlistHumble`; `--dump` saves `cache/humble/*` for parser tuning.
- **Nintendo Store wishlist fetcher** — new `nintendo_wishlist` Connections provider (CDP browser profile at `cache/auth/profiles/nintendo_wishlist`, separate from the eShop `nintendo` library path). `fetch_nintendo_wishlist.py` loads `nintendo.com/us/wish-list/` headlessly, parses `__NEXT_DATA__` and captured wishlist JSON, writes `games_wishlist_nintendo.json`. Manifest key `wishlistNintendo`; `--dump` saves `cache/nintendo/wishlist_dump.*` for parser tuning.
- **Auto-fetch on connect + stale-store refresh** — Connections prefs: **Auto-fetch when a store connects** (default on) runs that provider's fetcher keys on disconnect/expired → connected transitions (not first boot); **Auto-refresh stores older than 24h** (default off) quietly refreshes one stale store per ~30 min while the app is open. See `js/fetcher-health.js` and `tests/auto-fetch.test.js`.
- **Chip-level auth-failure backoff** — when a fetcher run ends in an auth-ish failure (401/403, expired cookie/session, rejected sign-in) the chip cools down with an escalating window on consecutive failures (5m → 15m → 60m). While cooling down the chip is disabled, shows an `auth Nm` badge + tooltip, and is skipped by both auto-refresh and the bulk "Run stale" sweep — closing the request-flood path against a provider that needs reconnecting. The cooldown clears on the next successful run, when the timer expires, or the moment the mapped provider shows "connected" in Connections (so reconnecting never leaves a chip stuck). Persisted across reloads.
- **PSN trophy completion pill** — library rows with `trophy_progress` show a slim muted `🏆 N%` pill in the game-name meta line (no new column); wishlist rows omit it.
- **SECURITY.md threat model** — formal local-first security model: trust-boundary diagram, protected assets, the at-rest crypto (AES-256-GCM with an OS-keychain key; scrypt N=2¹⁴ for the optional master password and the portable bundle), and an explicit out-of-scope list (local malware, plaintext `.env`/cookie jars, the `.master_key` fallback, storefront ToS). Linked from README and PRIVACY.md. Marketing suite gains a "Nothing to breach" security campaign and a founder-truth line on why local install _is_ the security posture.
- **Library count 1UP** — after a fetch adds games, the library / wishlist count rolls over ~1s with floating green "+N" popups (Mario 1UP / scrolling-combat-text style). Popups anchor on the right edge of the number, spawn ~70ms apart (up to 10 per burst) so several climb at once, and the rolling number uses `tabular-nums` so digits don't shift sideways as it counts. Only fires on fetch-driven _increases_, not filters or cold boot. Cancels cleanly on tab switch, view change, or `prefers-reduced-motion`. Chained fetcher landings (Steam, then GOG, then PSN) keep prior popups climbing instead of cutting them off mid-flight. Surfaces: Dashboard hero number and Library / Wishlist summary chips. Demos for screen recordings: load `index.html?demo=count` (six fake stores landing) or `?demo=count-small` (five `+1` bursts), or run `baklogDemoLibraryCount()` / `baklogDemoLibraryCountSmall()` from the console.
- **Portable secrets bundle** — passphrase-encrypted export/import of all Connections credentials plus CDP browser profile dirs (`auth/bundle.py`, format version 1: magic `BAKLOGSB`, scrypt + AES-GCM). Dashboard: Connections ⋮ → Portable bundle… → Export / Import. API: `POST /api/auth/secrets/export` and `POST /api/auth/secrets/import`. CLI: `python -m auth export-bundle` / `import-bundle` (with `--dry-run`). Import snapshots existing profiles to `cache/auth/profiles_pre_import_<timestamp>/` before overwrite. See PRIVACY.md.
- **Opt-in bug report submit** — kebab **Report a bug…**, error toast **Send report**, and `?debug=1` overlay open a consent dialog with payload preview. Explicit click POSTs the sanitized bug bundle to `https://baklog.app/api/report` (Supabase log + Resend email). **Copy instead** remains clipboard-only. See PRIVACY.md.
- **Local-only bug bundle** — sticky error toast and `?debug=1` overlay gain a "Copy bug bundle" button that puts a sanitized JSON payload on the clipboard (app version, view, data version, table fingerprint, filter count, last render time, session + persisted error log). Persisted log is a rolling 200-entry localStorage ring at `baklog-error-log`. Nothing is sent automatically. Kebab menu adds "Report a bug…" for the same bundle without needing a live error. See PRIVACY.md.
- **BAKLOG branding** — product title, favicon, README tagline, header subtitle (“Cross-store backlog · local-only”).
- **Deal badges** — price-dropped-since-last-ITAD (↓), all-time vs 1-year historical low, owned-elsewhere on dashboard deal cards.
- **Library cross-store pill** — “also on GOG · …” when deduped copies exist on multiple stores.
- **Export top 20 backlog** — ⋯ menu copies a Markdown table to clipboard.
- **Nintendo fetch** — clearer reconnect hint when session cookie expires (9001-1620).
- **Installer** — `dist/baklog` output folder and `Start BAKLOG.bat`.
- **Connections tab** — unified sign-in for all stores: form fields for API keys (Steam, Xbox, itch, ITAD), headed Chrome/Edge sign-in via CDP for cookie/OAuth providers (GOG, PSN, Epic, Battle.net, Nintendo, Ubisoft), encrypted at rest via OS keychain + AES-GCM (`auth/` package).
- **Reconnect banner** when a fetcher fails auth (401/403) — links to Connections tab.
- **`scripts/build_installer.ps1`** — bundles app into `dist/baklog/` (target machine needs Chrome or Edge for Connections).
- **Tracker Notes tab** — `tracker.html` gains a Notes panel for ops/guardrail reference (e.g. BAKLOG_PROFILE auto-ignore); moved out of Triage.

### Fixed

- **Fetchers overwriting saved play data with zeros on re-fetch** — `merge_cached_row` now keeps any populated authoritative field when the fresh API row is empty (except pricing, which may legitimately drop to free). Play dates are monotonic (`last_played` keeps the newer ISO timestamp, `first_played` the earlier). Fixes PSN `first_played` / `trophy_progress` loss when title-stats do not match. `fetch_humble.py` now merges rows like other library fetchers instead of full-replacing enrichment each run.
- **Blank library/wishlist rows right after boot curtain** — `reloadGames()` fetches store JSON in parallel; `liftBootCurtain()` nudges layout after reveal so table cells paint on hard refresh (library, wishlist, itch).
- **Hard refresh on itch tab jumped to dashboard** — itch→dashboard redirect is fail-open until `authStatusLoaded()` and `dashboardDataReady`; one authoritative check after bootstrap instead of clobbering the saved view mid-load.
- **Fetcher log did not stick to bottom** — explicit tail-follow flag re-pins after panel resize; clears the empty-state placeholder on first line flush.
- **Chart.js load failure surfaced as unhandled rejection** — dashboard view-overlay path catches `ensureChartJs()` rejections so a transient script error does not open the error toast.
- **Header controls clickable during boot** — fetcher status pill and profile menu are non-interactive under `data-boot-loading` (pointer-events + keyboard guard).
- **PSN cross-gen playtime** — `title_stats` for PS4 and PS5 (same game, different `title_id`) are now summed by dedupe name so titles like Fortnite keep both platforms' hours (~2304h + ~168h) instead of whichever `np_title_id` the trophy row matched that day.
- **EA fetch exit 4 after reconnect** — Connect now persists the ea.com web-session `EA_BEARER_TOKEN` (probed via Juno GraphQL) alongside the browser profile, so fetch no longer depends on headless re-sniff alone. Shared `ea_session.py` handles capture (deals + home triggers, `context.on('request')`); `EaCaptureError` maps to exit 1 without `mark_invalid`; `--headed` / `--dump-debug` for diagnosis.
- **Nintendo fetch empty after reconnect** — GraphQL responses are queued in the CDP `response` handler and parsed on the main thread (avoids deadlocking `getResponseBody` on the reader thread). Connect now requires eShop session cookies plus a valid `/api/auth/session` idToken. Capture failures raise `NintendoCaptureError` (exit 1, no `mark_invalid`) with `--headed` / `--dump-debug` hints; true session expiry still uses exit 4.
- **Fetcher console reconnect duplicated log lines** — each log line now has a monotonic `seq`; SSE emits it as `id:` and honors `?since=` / `Last-Event-ID` on replay. The client tracks `lastSeqByRunId` (sessionStorage) and resumes without re-appending the backlog after reload or stream drop.
- **Stale fetcher chips after missed `done` events** — `syncFromServer` reconciles `runStateByKey` against the server snapshot so chips and panel chrome cannot stay `running`/`queued` when the run already finished.
- **Cancel button double-submit** — disabled with a "Cancelling…" label while `cancelInFlightRuns` is in flight.
- **Run `line_count` under-reported past 25k lines** — `to_summary()` uses a dedicated `_total_lines` counter (deque still caps in-memory replay).
- **Nintendo eShop fetch rewired to browser GraphQL** — Nintendo retired the legacy REST endpoint (`/api/my/transactions` now returns 404 HTML), which the old client misread as a bad cookie and force-expired the Connections chip. `nintendo_client.py` now drives the saved CDP profile (`cache/auth/profiles/nintendo`) headlessly, intercepts the `TransactionsClientRootClient` Savanna GraphQL responses, paginates via the on-page numeric buttons, and maps rows to the legacy shape. `NintendoEndpointError` classifies 404/HTML as "endpoint moved" (exit 1, no `mark_invalid`); cookie-only with no saved profile raises a helpful reconnect error. `fetch_nintendo.py` passes `profile_dir("nintendo")`.
- **Fetcher console froze during large refreshes** — run-log lines now buffer and flush on `requestAnimationFrame` (`appendLine`/`flushLines`/`flushLinesNow` in `js/fetcher-health.js`) instead of a synchronous DOM append per SSE line; `clearLog` resets the buffer.
- **Run-log panel title/badge mismatch** — `syncLogPanelChrome` keeps the panel title and status badge aligned with real server state (no more "Running: Covers" under a "queued · launching" badge); queue position reads "2 of 2" (`activeCount + idx + 1`) instead of a confusing "1 of 2".
- **Co-op tag enrichment force-killed on silent stretches** — `enrich_steam_tags.py` prints a heartbeat every 25 Steam lookups so long quiet phases (e.g. Epic) aren't killed by the 180s server stall watchdog.
- **EA fetch argparse crash** — `fetch_ea.py` no longer registers `--allow-drift` twice (duplicate of `add_allow_empty_arg`), which prevented the EA dashboard chip and CLI from starting.
- **Humble fetch rejected `--skip-hltb`** — `fetch_humble.py` accepts the flag (no-op; HLTB stays off unless `--hltb`) so the manifest, `refresh.ps1`, and connection-matrix test commands match the script.
- **Fetcher cancel no longer leaves a ghost queue slot** — cancel waits for the server to finish before clearing chip state; suppressed runs are not hidden until terminal; duplicate submits while a run is still dying on `_active` are rejected; 409 responses re-sync the queue UI.
- **Profile menu vs BAKLOG_PROFILE in server shell** — `server.py` drops `BAKLOG_PROFILE` from the dev-server process at import so `profiles/index.json` and the header menu always own the active profile; startup prints a NOTE if the var was set. Per-run fetchers still pin profile via `subprocess_env_for_profile()`. CLI one-off fetchers in a separate shell are unchanged.
- **Multi-tab personal.json cross-write** — saves stamp the tab's bound profile id; server rejects mismatches (409) so a background tab cannot overwrite another profile's `personal.json`. Unload `sendBeacon` now reaches `POST /api/personal` (previously 404).
- **Delete profile no longer races in-flight runs** — DELETE is refused (409) while a fetch is running or queued for that profile. Switching profiles cancels runs and waits up to `SWITCH_CANCEL_WAIT_SEC` before rebinding paths.
- **Amazon launcher + web union-merge** — `fetch_amazon.py` no longer drops launcher-only titles when run with `--source web` (or vice versa). Each run refreshes only its source slice, keeps the other slice, and collapses cross-source duplicates by ASIN then name (launcher preferred). Drift guard is per-source slice, not whole-file count.
- **Steam fetch survives Store blips** — `fetch_games.py` reuses cached catalog rows when the Store API fails mid-run (playtime still refreshed from GetOwnedGames); missing-credentials message points to Connections instead of `.env`.
- **Library watch “found” banner** — no longer hidden immediately after a watched game appears in the Steam catalog.
- **Run queue can't wedge on a stubborn process** — the worker no longer blocks on `proc.wait()` forever. On cancel it re-issues the kill (Windows AppX Python can survive the first `taskkill`) and finalizes after a bounded `TERMINATE_GRACE_SEC` wait, logging and abandoning a lingering PID so the next queued run always advances.
- **Scatter chart pop-in on large libraries** — the HLTB-vs-rating scatter no longer appears in a single frame. Points animate in on their own (rise from the x-axis + pop from radius 0) at any library size, while the grid and axes stay still. Per-point color interpolation (the original chug source) remains off. Tab revisit replays the same points-only entrance.

### Changed

- **Fetcher progress heartbeats** — long pulls now emit consistent `[i/total] (NN%) phase` lines during previously-silent capture/batch steps (PSN library collect, GOG web catalog, itch owned-keys, Epic catalog pool, ITAD price batches, EA session/playtimes, Nintendo transactions, headless wishlist captures) and from enrichers, so the run console shows real progress instead of going quiet.
- **User-facing copy** — em dashes in UI strings replaced with `-` (empty-state placeholders, tooltips, toasts); code comments unchanged.
- **Dashboard spotlight portrait covers** — portrait art uses `object-fit: cover` again instead of letterboxed contain.
- **Fetcher log layout** — run log opens beside the fetcher health card (2/3 + 1/3 columns) instead of below, keeping the dashboard hero and combat-text count visible; console font 1px smaller; narrow viewports stack log under health.
- **Fetcher health hints** — missing-env warnings in the run log and Steam fetch scripts use plain “open Connections” guidance (`STEAM_CREDENTIALS_HINT` in `fetchers/_base.py`).
- **Connection matrix verification steps** — tracker text matches real behavior: Disconnect → Connect chip + blocked run; Reconnect → `python -m auth expire <provider>`; ITAD scope and HLTB flag wording corrected; EA session TTL aligned to registry (~30 days).
- **Connection matrix copy** — `tracker.html` testing steps rewritten in plain language (glossary for Reconnect, login vs setup errors, empty-result safety) and corrected to match the actual Connections controls: most cards expose only Connect/Disconnect/Reconnect (no editable cookie field), so the Reconnect test now uses the Disconnect button; only itch.io, ITAD, and Xbox have a key field to enter a wrong value.
- **Connections browser driver** — replaced Playwright with a lightweight Chrome DevTools Protocol (CDP) layer that launches the user's installed **Google Chrome** or **Microsoft Edge** (`auth/cdp_browser.py`). No `playwright install chromium` step; install is `pip install -r requirements.txt` only. Set `BAKLOG_CHROME_PATH` to override the browser executable.
- **Dashboard spotlight categories** — six new rotating hero eyebrows: On sale now (ITAD/Steam deal via `getDealInfo`), New release (last 12 months), Co-op campaign (`coop_online`, excludes `live`/`skip`), Couch co-op (`coop_local`), Long haul (HLTB ≥40h), Weekend-sized (8–15h). First-match priority places time-sensitive and co-op picks above the rating ladder.
- **Dashboard chart animation performance** — scatter no longer animates per-point colors; libraries over 200 points paint instantly; hover is rAF-throttled with spatial-hash hit tests (O(n) layout); line releases chart uses a shorter entrance; large scatter skips replay on tab revisit. CSS: huge-deal pulse uses opacity instead of filter; extended `prefers-reduced-motion` for fetcher/deal/scatter pulses.
- **Accessibility audit (bs_a11y)** — Lighthouse-aligned axe-core gate in CI (`tests/a11y/index-axe.test.js`); skip-to-main link + `<main id="main">`; focus trap/Escape on filter drawer, Connections popover, and modals; `aria-current` view tabs; co-op filter radiogroup pattern; contrast bump (`text-slate-500` → `text-slate-400` on slate-800); global `:focus-visible` outline.
- Fetch scripts read credentials from encrypted store first, then `.env` fallback (`auth.resolve_env`).

### Added (fetcher observability)

- **Fetcher observability hardening** — shared progress helpers (`fetchers/_progress.py`), start/end timing footers on all fetch/enrich scripts, heartbeats during long silent phases (HLTB cache skips, itch pagination, ITAD lookup, cover enrichment thread pool).
- **Server stall watchdog** — `server.py` emits `[server] no output for Ns — still running` when a subprocess is quiet for 30s (repeats every 60s).
- **`--allow-empty` flag** on GOG/Epic wishlist, Steam wishlist, Xbox, Epic library, GOG library, Steam library, PSN library, and ITAD fetchers — default refuses to overwrite JSON when zero items are returned (exit 2).
- **Reviews `--retry-misses`** — Shift+click on the Reviews chip re-attempts rows cached as no Steam app match (parity with HLTB/Covers).
- **Manifest `requires`** for Steam library, WL Steam, ITAD, and Reviews chips (missing-env warnings in Fetcher health).

### Changed

- HTTP failures in GOG wishlist product/price fetch, Steam cover search, Steam review search, and Ubisoft catalog batches now log status + URL instead of failing silently.
- HLTB enricher heartbeats during cached-miss skips as well as network lookups.

## [0.6.0] - 2026-05-30

### Added

- **`server.py` dev server** — replaces `python -m http.server` as the recommended
  way to run the dashboard on http://localhost:8765. Serves static files and
  exposes a small API: `POST /api/run/<key>` queues a fetcher, `GET
/api/stream/<run_id>` streams stdout/stderr over SSE, `GET/PUT
/api/personal` reads/writes `data/personal.json`. Runs are serialized through
  a single-worker queue; fetcher argv is whitelisted server-side.
- **Fetcher health row (dashboard)** — compact chip strip for all 25 fetchers
  (12 library + 8 wishlist + ITAD + 4 enrichers) with freshness coloring, entry
  counts, and an "Only stale / missing" toggle. When `server.py` is running,
  chips become buttons that enqueue the matching fetch script and open a live
  log panel below the row.
- **Server-backed personal data** — statuses, notes, priorities, tags, UI
  prefs, and manually-added games persist to `data/personal.json` (atomic
  writes + rolling backups in `data/personal_backups/`). Browser
  `localStorage` remains a hydration cache; server wins on boot. One-time
  migration banner offers to upload existing localStorage data when the server
  file is empty.
- **Filter drawer keyboard shortcuts footer** — always-visible two-row hint
  (`/` search, arrows, Enter, Esc, library status keys, priority, Space select)
  pinned to the bottom of the filter drawer.
- **Dashboard chart polish** — status/review donut palette tuned (backlog red,
  playing yellow, unfinished orange, finished green; Unreviewed grey); Top
  genres and Backlog hours by store unified (sorted bars, rounded ends, end
  labels, inline backlog legend); Releases by year switched to area chart with
  3-year rolling average and era bands; HLTB vs Steam rating scatter uses
  amber-to-emerald rating gradient; KPI strip adds Wishlist count and fits nine
  tiles on one row at xl widths.
- **Co-op spotlight (dashboard)** — replaced the old "Personal tags" bar chart
  with a full-width Co-op spotlight card laid out as a head-to-head versus:
  Online co-op on the left (blue-tinted side panel, blue-gradient hover) and
  Couch co-op on the right (emerald-tinted side panel, emerald-gradient
  hover), with a thin central unifier strip that shows Total co-op and Both
  flavors stats. Each side panel surfaces its own big count, Backlog /
  Finished / Avg HLTB numbers, and a three-row "Top unplayed picks" list
  (cover thumb, name, Steam rating %), all sorted by review score. The
  whole side panel is clickable (`role="button"` + Enter/Space keyboard
  support) to drill into the library with the matching co-op filter; the
  pick rows short-circuit the side click and focus the individual game
  instead. Empty-state copy guides the user back to `fetch_games.py` if no
  co-op flags are detected. The `dashDrillTag` helper and `chartTagsBar`
  block are gone (personal tags are still filterable via the drawer, just
  no longer charted on the dashboard).
- **Per-view sort persistence** — Library, Wishlist, and itch.io each now
  remember their last-used column sort across reloads. New `prefs.viewSorts`
  object stores `{ key, dir }` per view; the column header click handler
  persists it via a new `persistCurrentSort()` helper, and both
  `bootstrap()` and `switchView()` restore the right sort on entry through
  `applySavedSortForView()`. Also fixes a pre-existing cross-contamination
  bug: sorting Library by `hltb_main_hours` and then hopping to Wishlist no
  longer leaves Library stuck on `deal_price` when you come back. The old
  one-shot `wishlistSortVersion` migration is gone — wishlist's "cheapest
  first" preference is now just the default value of `viewSorts.wishlist`
  (`deal_price` asc), overrideable by any column click.
- **Co-op signal (Steam)** — `fetch_games.py` and `fetch_wishlist.py` now parse
  Steam's `categories` array into structured `coop_online` and `coop_local`
  booleans on every row. "Online Co-op" and "LAN Co-op" set `coop_online`;
  "Shared/Split Screen Co-op" sets `coop_local`. The bare "Co-op" category is
  intentionally ignored because the flavor is unknown. The category cap was
  also raised from `[:8]` to `[:16]` so co-op tags can't be silently truncated
  when a game ships with a lot of leading achievement/cloud-save flags.
  Existing JSON files (`games_steam.json`, `games_wishlist.json`) were
  backfilled in-place from the data already present in the `tags` array, so no
  refetch is required to see the new pills.
- **Co-op row pills** — the table title cell now renders a blue `ONLINE`
  pill and/or an emerald `COUCH` pill (right after the EA pill) whenever the
  matching co-op flag is set, mirroring the visual weight of the existing
  Early Access pill.
- **Co-op filter toggles** — the filter drawer gained a Co-op section with
  two checkboxes ("Online co-op", "Couch co-op"). Each acts as an AND filter
  (check both to require games that support _both_ flavors), produces a
  matching active-filter pill ("Online co-op" / "Couch co-op"), and is
  cleared by both the per-pill × button and the Clear-all sweep. Filters
  feed into the same `table-query.js` worker pipeline as the rest of the
  drawer so the virtual table stays responsive.
- **Early Access filter toggle** — new "Early Access only" checkbox in the
  filter drawer (with an inline `EA` pill so its function is obvious). Hides
  every non-EA game across Library, Wishlist, and itch.io. Adds a matching
  active filter pill ("Early Access only") that the Clear-all sweep and the
  per-pill × button both reset. Detection reuses the same `isEarlyAccess`
  helper that drives the cover ribbon and table pill — now exported from
  `table-query.js` so the worker thread can use it too (the duplicate copy in
  `app.js` was removed to prevent drift).
- **Wishlist source filter chips** — the filter drawer now shows an "All ·
  Steam · GOG · Epic" chip row whenever the Wishlist tab is active (mirroring
  the Library tab's Store chips). Picking a chip filters the wishlist table
  by `wishlist_store`, adds a "Wishlist source: …" pill to the active filter
  bar, and persists across reloads via the `wishlistStoreFilter` pref. Manual
  wishlist entries still appear under "All".
- **Early Access badge** — games tagged "Early Access" (e.g. _Hyper Light
  Breaker_, _Slay the Spire 2_) now wear a Steam-style amber ribbon across the
  bottom of their cover art on the dashboard pick cards, deal hero card, and
  wishlist deal cards, plus a small `EA` pill next to the title in the main
  table. Detection is data-driven: any genre/tag containing "early access" or
  an explicit `early_access: true` flag triggers the badge — no extra fetch
  pass required.
- **Epic Games Store wishlist** fetcher (`fetch_epic_wishlist.py`) — uses the
  storefront session cookie (`EPIC_STORE_COOKIE` in `.env`) to query
  `www.epicgames.com/graphql`. Required because Epic discontinued
  `graphql.epicgames.com` and the launcher OAuth bearer can't reach the
  storefront. Results merge into the dashboard Wishlist tab and deal radar
  alongside Steam + GOG entries.
- `epic_client.EpicStoreClient` — cookie-based storefront GraphQL client.

### Changed

- **Dashboard `Top rated unplayed` and `Quick wins` rows are now clickable.**
  Each row in those two list cards is rendered as a button that calls
  `focusGame()` — clicking a game flips you to the Library tab, scrolls the
  matching row to the center of the table, and highlights it (same plumbing
  used by the deal hero and steals list).
- **Top deal card got a hero treatment.** The "Today's top deal" cover jumped
  from 52×78 to 92×138, the name now wraps to two lines instead of truncating,
  the price font is bumped, and a stat strip below the badges shows review%
  and HLTB main hours as pills with genres as plain text on a second line.
- **Wishlist deal cards fill their grid row.** All three dashboard deal cards
  now stretch to match the tallest column (driven by the steals list). The top
  deal meta column distributes name/price, badges, and stats top→middle→bottom;
  the sale scoreboard pins its cut-distribution bar to the card floor; the
  steals footer anchors to the bottom — so short and tall rows both look
  balanced instead of leaving dead space or crowded pill stacks.
- **Sale scoreboard stats are larger** and now include a **cut distribution**
  strip beneath the numbers: a horizontal stacked bar splitting wishlist sale
  items into Light (<25%) · Medium (25-49%) · Deep (50-74%) · Huge (75%+),
  with a labelled legend underneath showing each bucket's count. Lets you see
  at a glance whether your wishlist is full of mild sales or deep ones.
- **Wishlist deal cards revamped** — the dashboard's two scoreboard cards next
  to "Today's top deal" got real upgrades:
  - **Saved by waiting → Sale scoreboard.** The hypothetical "$70 you'd save
    if you bought everything" dollar figure was replaced by three actionable
    stats: `On sale 8 / 30`, `Avg cut -25%`, `Best cut -75%` (with the
    leading game's name as a caption). Click still drills to the
    on-sale-only wishlist view.
  - **Steals waiting → mini-list.** The big "4" + three thumbs were replaced
    with up to six clickable rows (cover · name · ★ if historical low · cut%
    · price). Each row jumps straight to that wishlist entry; the footer
    `+N more · view all →` still applies the steals filter (50%+ off or
    historical low, 80%+ rated).
- Wishlist row/pick badges now show the plain source-store letter (S/G/E/…)
  instead of a stacked `W*` glyph. The tooltip still reads "Wishlist · STORE".
- Dashboard itch.io recap pie chart now reflects the stats shown (rated games,
  unrated games, non-game items) instead of a personal-status breakdown.
- Header meta strip now consolidates wishlist counts into one entry
  (`Wishlist 30 (S 29 · G 0 · E 1)`) instead of three separate entries —
  scales as more stores are added.
- `state.libraryMeta` initial keys now cover every store (xbox, battlenet,
  ubisoft, wishlistGog, wishlistEpic, itad, hltb) for consistency.
- **Default local URL** — README and stack table now recommend
  `python server.py` → http://localhost:8765; plain `http.server` documented
  as read-only fallback.
- **`enrich_hltb.py`** — writes `fetched_at` into `cache/hltb_map.json` on
  save; dashboard HLTB fetcher-health chip falls back to the file's HTTP
  `Last-Modified` when the field is absent.

### Fixed

- **Bulk selection now works on Wishlist + itch.io tabs.** Previously the
  row-select checkboxes were rendered only when `activeView === "library"`
  and the bulk action bar refused to open elsewhere, so the column-header
  "select all visible" checkbox effectively no-op'd on those tabs. The per-row
  checkbox is now rendered in all table views and the bulk bar opens
  whenever there's at least one selection (any non-dashboard view).
- **Bulk status buttons now match the active tab.** The bottom bulk bar
  previously always showed all seven library statuses (Playing, Unfinished,
  Live service, …) even on Wishlist, where row dropdowns only offer Watching /
  Want it / Pass / Bought. Status buttons are rendered per view from shared
  label maps (`STATUS_LABELS` for Library + itch.io, `WISHLIST_STATUS_LABELS`
  for Wishlist) so bulk-set values always align with what each row can display.
- **"Select all visible" now visually checks every row.** The select-all and
  bulk-clear handlers updated `state.selectedKeys` but `renderTable()`
  short-circuited on the unchanged fingerprint, so the per-row boxes never
  re-painted. Each selection-mutation site (`selectAllVisible`, `bulkClear`,
  `bulkSetStatus`, `bulkSetPriority`) now calls `invalidateTableCache()`
  before re-rendering, so the table redraws with the new checkbox state.
- **HLTB enrichment now covers Xbox, Battle.net, Ubisoft, and Nintendo.**
  `enrich_hltb.py`'s `STORE_FILES` list was stale and silently skipped those
  four `games_*.json` files, leaving `hltb_main_hours` null on every entry.
  The Dashboard "Backlog hours by store" chart consequently showed empty bars
  for those stores. Added them to the loop so a single
  `python enrich_hltb.py` pass now backfills hours for all stores.
- **Dashboard wishlist cards no longer surface "fake" historical lows.**
  Newly released wishlist games whose price has never dropped were appearing
  in "Today's top deal" and "Steals waiting" because ITAD/Steam still reports
  `is_historical_low: true` for any never-discounted current price (e.g.
  _Mina the Hollower_, _MOUSE: P.I. For Hire_). `isStealDeal` and
  `wishlistGamesWithDeals` now require `cut > 0` first, so the dashboard only
  shows games that are genuinely on sale. The full wishlist tab still keeps
  the historical-low badge for those entries — it's just no longer flagged as
  a steal on the dashboard.
- **Fetcher SSE log panel on Windows** — `ConnectionAbortedError` when the
  browser closes an EventSource is handled gracefully; client reconnects to
  active/queued runs via `/api/runs` instead of showing a blank log.
- **Dashboard loading overlay** — `.dash-card { display: flex }` no longer
  overrides Tailwind `.hidden` on `#dashboardLoading`.
- **KPI row wrap** — nine KPI tiles stay on one row at xl (`xl:grid-cols-9`).

### Removed

- **Metacritic score** column, schema field (`metacritic_score`), and Steam
  `appdetails.metacritic` ingestion. Only Steam provided values, coverage was
  sparse (~10% of the Steam library; 0% of every other store), and the field
  doubled as a misleading signal next to Steam's own review %. Steam review %
  is now the single source of truth for rating. Existing
  `metacritic_score` fields are stripped from `games_*.json` on next fetch and
  the dashboard ignores any cached values.

## [0.5.1] - 2026-05-29

### Added

- Virtual scrolling for large tables (80+ rows): only visible rows are painted
- Web Worker filter/sort for libraries with 500+ games
- Shared row `<select>` templates and memoized `getPersonal()` lookups

### Changed

- `#tableWrap` is vertically scrollable with sticky header; compact `.row-ctl` selects
- Dashboard chart timers cancelled when leaving the dashboard tab (avoids stray renders)

## [0.5.0] - 2026-05-29

### Added

- **Phase 0 refactor:** `js/state.js` + `js/app.js` (ESM); dashboard logic moved out of inline `<script>`
- `shared/json_util.py` — strips null enrichment stubs when writing `games_*.json`
- `fetchers/_base.py` — shared fetcher helpers (stdout, HLTB/dry-run args, cache merge, JSON write)
- `enrichers` package — `python -m enrichers hltb|steam-reviews|cross-store-images`
- `pyproject.toml` + `tests/` (pytest for JSON slim + dedup name normalization)
- `tools/split_index_js.py` — re-extract script from HTML if needed

### Changed

- `fetch_itch.py` uses `fetchers._base` and slim JSON output

## [0.4.0] - 2026-05-29

### Added

- **Dashboard tab** (default view): Chart.js analytics with store/status/review donuts, genre and tag bars, backlog-hours-by-store stacked bar, HLTB histogram, releases timeline, HLTB-vs-rating scatter (log x-axis), wishlist deal stats, top-rated unplayed and quick-wins lists, itch.io recap card
- Per-view table render cache: instant tab switching when filters/sort/data unchanged
- `formatNum()` helper: comma-separates values with 5+ digits (KPIs, summary chips)
- PSN `psn_platforms` field; frontend `NON_GENRE_TOKENS` blocklist so platform labels never appear in genre charts
- itch.io fetcher merge preservation (`FETCHER_AUTHORITATIVE`, `_merge_cached_row`) and `--dry-run` flag

### Changed

- Score column toggle uses CSS class flip (`.table-hide-score`) instead of full table rerender
- Untouched games count as **Backlog** in status chips and dashboard donuts (removed misleading "No status" slice)
- HLTB histogram bars shade green→red by bucket; backlog-hours bars use store brand colors with bright cyan **Playing** segment
- itch.io recap moved into the 3-list row beside Quick wins; "Recently completed" card removed
- Dashboard legend labels use white text; custom backlog-hours legend uses `fontColor`
- `fetch_psn.py`: platforms stored in `psn_platforms`, not `genres`
- `fetch_games.py` writes only `games_steam.json` (dropped legacy `games.json` dual-write)
- File picker menu label: **Load Steam JSON…**
- Tailwind rebuilt with responsive variants (`md:`, `sm:`, `xl:`); removed dashboard `.dash-grid` workaround CSS
- Table render uses single `innerHTML` batch + delegated row-click handler

### Removed

- `enrich_steam_images.py` (superseded by `enrich_cross_store_images.py`)
- `patch_store_urls.py` (one-shot URL fix, complete)
- Legacy `games.json` auto-fetch fallback in dashboard

## [0.3.1] - 2026-05-29

### Added

- Epic Games library fetcher (`fetch_epic.py`, `epic_client.py`)
- Amazon Prime Gaming fetcher (`fetch_amazon.py`, `amazon_client.py`) via local SQLite
- Xbox / Game Pass / Microsoft Store fetcher (`fetch_xbox.py`, `xbox_client.py`) via OpenXBL
- Battle.net fetcher (`fetch_battlenet.py`, `battlenet_client.py`) via unofficial cookie scrape
- Ubisoft Connect fetcher (`fetch_ubisoft.py`, `ubisoft_client.py`) via unofficial API headers
- Nintendo Switch fetcher (`fetch_nintendo.py`, `nintendo_client.py`) via eShop transactions (~2yr history; older/cartridge = manual Add Game)
- itch.io quarantine tab: `itchGames` array separate from `allGames`; Top Rated picks only; summary chip shows game count vs total keys
- itch.io non-game filter pill ("Hide tools, soundtracks, etc.") default-on; fetcher imports all owned keys
- Live service status in row dropdown, bulk toolbar, sidebar filter, and keyboard shortcut (`L`)
- A–Z jump nav pinned to right edge (`#` bucket for non-letter titles); dims unused letters
- Status breakdown chips in Library and itch.io summary rows (click to filter by status)
- Wishlist Deals tab sorts by post-sale price ascending (cheapest first)
- Deal discount badge styling tiers: ≥50% gradient glow, ≥75% animated gradient
- `enrich_steam_reviews.py --stores itch` backfills Steam review % on itch.io game-class rows
- `enrich_hltb.py` backfill script for any `games_*.json` row missing HLTB hours

### Changed

- Top-stats itch.io chip on Library tab shows videogame count only (not TTRPG/tools total)
- `refresh.ps1` clears log before run, includes itch Steam-review enrich step
- `.gitignore` covers Xbox, Battle.net, Nintendo, Ubisoft, GOG wishlist JSON outputs
- README documents all 11 data sources and enrichment scripts

### Added (earlier unreleased)

- Wishlist becomes a deal radar: dedicated drawer section with On sale only, Historical low only, Hide already-owned (cross-store), Min discount %, and Max price filters
- Default sort on first wishlist visit is Discount % desc, plus a deal-stat row count (e.g. "12 on sale, 3 at historical low")
- New "Wishlist Deals" Picks tab ranks wishlist items by deal score (discount + historical-low bonus + rating bonus, owned-elsewhere penalty); clicking a card switches view and focuses the row
- "+ Add game" modal grew an "Add to Wishlist" mode with optional price, discount %, and store URL fields, persisted via `manualGames` with a `wishlist: true` flag
- GOG wishlist fetcher (`fetch_gog_wishlist.py` → `games_wishlist_gog.json`) using the existing `GOG_AL` cookie; entries merge into the Wishlist tab with a GOG-tinted "WG" badge
- Wishlist row badges now indicate the target storefront (S/G/E/P/A/N/X/I/M)
- Wishlist polish: ITAD-aware Price sort, deal-aware CSV export, view-specific summary pills, library-only filter drawer sections, wishlist Tracking status column, Pick for me prefers on-sale items, manual discount-only entries pass max-price filter
- PlayStation library fetcher (`fetch_psn.py`, `psn_client.py`) using NPSSO token auth via `psnawp`
- PSN store filter chip, badge, and summary counts in the dashboard
- Trophy progress and platform tags on PSN rows
- itch.io owned-games fetcher (`fetch_itch.py`, `itch_client.py`) + dashboard chip/badge
- Slim toolbar with filter drawer, active filter pills, and kebab menu for data actions
- Personal free-form tags per game with filter chips, bulk tag add, picks integration, CSV export
- Bulk row selection with status/priority bar; cleanup mode filter; keyboard shortcuts
- Steam wishlist tab (`fetch_wishlist.py` → `games_wishlist.json`) with “already owned” hints
- IsThereAnyDeal prices (`fetch_itad.py`, `itad_client.py` → `itad_prices.json`) in Price column
- Cross-store cover backfill (`enrich_cross_store_images.py`) via Steam store search

## [0.3.0] - 2026-05-28

### Added

- GOG library fetcher (`fetch_gog.py`, `gog_client.py`) using session cookie auth
- Multi-store dashboard: load `games_steam.json` + `games_gog.json`, store filter chips, store badges
- Namespaced personal data keys (`steam:<id>` / `gog:<id>`) with automatic migration from v0.2

### Changed

- Steam fetcher writes `games_steam.json` and adds `store` / `id` fields on every game row
- Dashboard title and summary pills show per-store counts

## [0.2.0] - 2026-05-27

### Added

- Compact top layout with tabbed Picks panel (Top Rated, Next Up, Quick Wins, Hidden Gems)
- Pick-for-me randomizer, reload button, multi-select genre filters, and score column toggle
- Priority Score sorting, hidden-gem badge, status row colors, and persistent multi-row expansion
- Inline HLTB main-hour override and compact Main/Extra/Completionist display
- Price/discount support in store JSON and Price column in the dashboard
- Weekly automation helper script (`refresh.ps1`) and updated README docs

## [0.1.0] - 2026-05-27

### Added

- Python fetcher for Steam library (owned games, store metadata, review scores)
- HowLongToBeat integration for game length estimates
- Local HTML dashboard with sort, filter, status, notes, and priority
- On-disk API cache for faster re-runs
- GitHub repo and local-only workflow (no hosting)
