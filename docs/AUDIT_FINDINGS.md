# BAKLOG full-project audit findings

Audit date: 2026-06-03. Method: section-by-section review (14 areas: trust boundary → perf/a11y). Prior hardening items in [tracker.html](../tracker.html) `HARDENING_LOG` treated as baseline (already addressed).

**Operator context:** Store fetchers are largely broken today (API drift, auth churn). Section 6 records inventory and classification only — not a mandate to fix every store in this pass.

## Summary

| Severity | Count | Notes |
|----------|-------|--------|
| Blocker | 0 | — |
| Should-fix | 4 | 3 fixed in this pass; 1 deferred (Epic callback wiring) |
| Nice-to-have | 8 | Refactors, Phase 6, fetcher repairs |
| Pass (verified) | 40+ | See per-section tables |

### Fixes applied in this audit pass

1. **`_bind_request_user`** — single bearer→profile path for API auth and static data gates ([server.py](../server.py)).
2. **`cancel_all` / `force_reset` profile scoping** when Supabase auth is on ([server.py](../server.py), test `test_cancel_all_scoped_to_active_profile`).
3. **[SECURITY.md](../SECURITY.md)** — optional Supabase auth reflected in TL;DR and trust boundary.
4. **`npm run vendor:supabase`** — rebuild vendored Supabase JS ([package.json](../package.json)).
5. **Connections 3-state pills** — removed client-side "Connecting…" animation; `displayStatus()` in [js/connections.js](../js/connections.js) maps `expired` → pill "Not connected" while server `expired` + fetcher-health reconnect logic unchanged; post-connect refresh via `BroadcastChannel` + time-boxed fast poll.

---

## Section 1 — Trust boundary and exposure

| Invariant | Status | Evidence |
|-----------|--------|----------|
| Mutating routes CSRF-guarded when auth off | pass | `_csrf_allowed`, `baklogFetch` sets `X-BAKLOG-Local` |
| Valid Bearer bypasses CSRF when auth on | pass | `_csrf_allowed` + [tests/test_server_csrf.py](../tests/test_server_csrf.py) |
| Static deny: `.env`, `profiles/`, `cache/auth/` | pass | `_static_class` |
| Catalog JSON requires bearer when auth on | pass | `_gate_static` → `_bind_request_user` |
| SSE requires single-use ticket when auth on | pass | `_authorize_stream`, stream-ticket tests |
| Access log redacts Bearer, Cookie, ticket | pass | `_LOG_REDACT_PATTERNS` |
| Server binds `127.0.0.1` only | pass | `HOST = "127.0.0.1"` |

| Finding | Severity | Fix |
|---------|----------|-----|
| Epic `/oauth/epic/callback` + `_epic_oauth_states` never registered in production (Playwright + paste flow) | fixed | Wired: `POST /api/auth/epic/oauth-url` mints a profile-bound `state` and returns an Epic login URL whose `redirectUrl` points back to the callback (`build_epic_oauth_login_url`). Callback now reachable, state-validated, profile-bound. Frontend: "Sign in with your browser instead" in the Epic fallback drawer. Playwright auto-capture remains the default. |
| `force_reset` still clears global `queue.json` when auth on | deferred Phase 6 | `p6_multiuser_run_queue` — per-user queue files |
| `cancel_all` now scoped to active profile when auth on | fixed | `cancel_all(profile_id=…)` |

---

## Section 2 — Auth, secrets, profile isolation

| Invariant | Status | Evidence |
|-----------|--------|----------|
| Corrupt secrets → no silent empty doc | pass | `SecretsCorruptError`, atomic save tests |
| Browser-auth worker inherits profile context | pass | `contextvars.copy_context()`, `test_auth_manager_profile` |
| Fetcher subprocess pins `BAKLOG_PROFILE` | pass | `subprocess_env_for_profile`, run profile tests |
| JWT requires `iss`, `sub`, `exp`, audience | pass | [shared/supabase_auth.py](../shared/supabase_auth.py) |
| Export corrupt → 400 not 500 | pass | `_handle_auth_secrets_export` |
| Bearer bind deduplicated | fixed | `_bind_request_user` |

| Finding | Severity | Fix |
|---------|----------|-----|
| Auth SSE (`/api/auth/*/stream`) not bound to profile beyond ticket on run streams | deferred Phase 6 | In-memory sessions; single-user self-host OK today |

---

## Section 3 — Server monolith and API surface

| Invariant | Status | Evidence |
|-----------|--------|----------|
| Profile create/rename/delete/switch blocked when account auth | pass | `_profile_admin_blocked()` |
| Personal corrupt → 503 | pass | `test_server_personal` |
| Single-instance port guard | pass | `test_server_single_instance` |
| `BAKLOG_PROFILE` stripped in server process | pass | `_release_server_profile_env` |

| Finding | Severity | Fix |
|---------|----------|-----|
| [server.py](../server.py) ~4.7k lines (Handler + RunManager + gates) | nice-to-have | Extract `run_manager.py`, `static_gate.py` in follow-up PRs |
| `do_PUT`/`do_DELETE` routing — verify all paths call `_require_api_auth` | pass | Spot-checked; all API mutations behind gate |

---

## Section 4 — Data integrity and persistence

| Invariant | Status | Evidence |
|-----------|--------|----------|
| personal.json backup restore | pass | `_restore_personal_from_backup` |
| Atomic catalog writes | pass | `fetchers/_base.py`, `test_safe_write` |
| Merge preserves enrichment | pass | `test_carry_enrichment`, per-store merge tests |
| Profile delete blocked with in-flight runs | pass | `test_profile_delete_runs` |

| Finding | Severity | Fix |
|---------|----------|-----|
| Legacy root layout vs `profiles/default/` | pass (documented) | README + SUPABASE_AUTH migration §3 |

---

## Section 5 — Fetcher runtime and queue

| Invariant | Status | Evidence |
|-----------|--------|----------|
| Queue crash-safety / duplicate prevention | pass | `test_run_manager` |
| Max runtime / subprocess job object | pass | HARDENING_LOG, `test_max_runtime_cap_kills_run` |
| Log redaction in runs | pass | `test_server_log_redact` |
| Auth exit 4 → reconnect UX | pass | `test_fetcher_auth_exit`, fetcher-health |
| Manifest ↔ scripts audit | pass | `test_fetcher_manifest_audit` |
| SSE reconnect mints fresh ticket | pass | `subscribe` → `urlWithStreamTicket` each connect |

| Finding | Severity | Fix |
|---------|----------|-----|
| Global `active.json` / `queue.json` shared across profiles | deferred Phase 6 | tracker `p6_multiuser_run_queue` |

### Section 5b — Connection matrix (UI / API graph)

Full inbound/outbound map: **[FETCHER_CONNECTIONS.md](FETCHER_CONNECTIONS.md)** (2026-06). Covers HTTP/SSE, `bind-events` chip and bar wiring, lifecycle polls, and post-run reload.

**Dashboard fetcher chrome:** `#fetcherRow` with collapsed `.fh-bar` (live status + log tail) and expanded health chips + `#fetcherRunLog`. Pref `fetcherCollapsed` (default true). Bar toggle is a single `<button data-role="bar-toggle">` with `aria-expanded` (no nested interactive controls).

---

## Section 6 — Store integrations (known-broken context)

**Scope:** Breadth inventory + auth/error classification — **not** fixing every store now.

| Store family | Auth path | Tests present | Audit note |
|--------------|-----------|---------------|------------|
| Steam | API key | yes | Generally stable; network tests optional |
| GOG web / Galaxy | cookie / local DB | yes | Galaxy platform-guarded |
| PSN | NPSSO | partial | Session-sensitive |
| Epic library | Playwright + auth code | yes | Callback route legacy; runner is live path |
| Epic wishlist | CDP profile | yes | GraphQL / CF sensitive |
| Xbox / OpenXBL | API key + cookie | partial | |
| Nintendo lib / wishlist | CDP GraphQL | yes | High churn (documented in HARDENING_LOG) |
| Amazon launcher / web | DPAPI / CDP | yes | Windows-only launcher |
| itch web / butler | API / local DB | yes | |
| Humble | CDP | yes | |
| EA | session | yes | ToS posture in SECURITY.md |
| Battle.net / Ubisoft / ITAD | OAuth / keys | partial | |

| Finding | Severity | Fix |
|---------|----------|-----|
| Many fetchers failing in production (operator-reported) | known state | Track per-store in tracker; fix store-by-store when APIs stable |
| CDP smoke workflow scope limited | nice-to-have | Document which providers [cdp-smoke.yml](../.github/workflows/cdp-smoke.yml) covers |

**When repairing fetchers:** prefer classifying errors (transient vs `mark_invalid`) over blanket reconnect; keep profile-scoped cache paths.

**Static fetcher audit (2026-06-05):** Python fetch scripts + dashboard fetcher-health UI reviewed without live connections. Findings, P0/P1/P2 fixes, and deferred refactors: **[FETCHER_AUDIT.md](FETCHER_AUDIT.md)**.

---

## Section 7 — Enrichment and catalog merge

| Invariant | Status | Evidence |
|-----------|--------|----------|
| Enrichers dry-run safe | pass | `test_enrich_steam_tags` dry-run |
| Dedup keys stable | pass | `test_dedup`, `game-core` tests |
| Manifest skip-hltb on fetch | pass | `fetchers/manifest.json` |

No new findings.

---

## Section 8 — Frontend bootstrap and API layer

| Invariant | Status | Evidence |
|-----------|--------|----------|
| Auth gate before bootstrap | pass | `app.js` + `auth-gate.js` |
| Config failure keeps gate | pass | `auth-gate.test.js` |
| Mid-session re-auth reloads | pass | `onAuthenticated` |
| Bearer on `dataFetch` / `baklogFetch` | pass | `api-client-auth.test.js` |

No new findings.

---

## Section 9 — Frontend mega-modules (refactor backlog)

| Module | Lines | Split candidates | Priority |
|--------|-------|------------------|----------|
| [js/fetcher-health.js](../js/fetcher-health.js) | ~4.5k | `run-console.js`, `run-queue.js`, `run-sse.js` | medium |
| [js/app.js](../js/app.js) | ~4.1k | `boot.js`, `tabs.js`, `library-reload.js` | medium |
| [js/connections.js](../js/connections.js) | ~3.4k | `connections-providers.js`, `connections-auth-sse.js` | low |

| Finding | Severity | Fix |
|---------|----------|-----|
| `render-gate` / fast tab switches | pass | Existing deferral tests |
| No Vitest for full `connections.js` auth SSE | nice-to-have | Add focused test with mocked EventSource |

---

## Section 10 — Cross-store UX and data model

| Invariant | Status | Evidence |
|-----------|--------|----------|
| Personal store profile-scoped | pass | `personal-store-profile.test.js` |
| Profile switch cancels runs | pass | `test_profile_switch_cancel` |
| FX / deals | pass | `deals-fx.test.js`, `test_fx` |

No new findings.

### Store display hierarchy

The business-card storefront watermark is the canonical display hierarchy:

1. Steam
2. Epic
3. GOG
4. Humble
5. itch.io
6. PlayStation
7. Xbox
8. Nintendo
9. Amazon
10. Battle.net
11. Ubisoft
12. EA

Three distinct, intentionally separate store orderings exist — do not collapse them:

| Constant | Location | Scope |
|----------|----------|-------|
| `STORE_DISPLAY_ORDER` | [js/dashboard-shared.js](../js/dashboard-shared.js) | Display hierarchy: dashboard hero badge strip + library summary chips. Mirrored by `BIZCARD_STORES` ([tracker.html](../tracker.html)) and the landing hero strip ([landing/index.html](../landing/index.html)). |
| `STORE_PRIORITY` | [js/game-core.js](../js/game-core.js) | Cross-store dedup survivor selection only — unchanged. |
| `RAIL_ORDER` | [js/connections.js](../js/connections.js) | Connections rail ease-of-use ordering only — unchanged. |

Tests: [tests/store-display-order.test.js](../tests/store-display-order.test.js).

---

## Section 11 — Testing and CI

| Layer | Status | Gap |
|-------|--------|-----|
| Python pytest | pass (Ubuntu/Win/macOS) | JWKS verify not hit in CI (no network) — acceptable |
| Vitest | pass | Full boot + auth + library integration optional |
| CDP smoke | separate workflow | Scope vs 15+ browser providers |

Added: `test_cancel_all_scoped_to_active_profile`.

---

## Section 12 — Documentation

| Doc | Status |
|-----|--------|
| SECURITY.md | fixed (Supabase optional auth) |
| PRIVACY.md | pass (already mentions Supabase) |
| README.md | pass |
| CHANGELOG.md | pass (Supabase in Unreleased) |
| SUPABASE_AUTH.md | pass |
| tracker Phase 6 | pass (`p6_multiuser_run_queue`) |

---

## Section 13 — Dependencies

| Item | Status | Note |
|------|--------|------|
| `js/vendor/supabase-js.mjs` | pass | Pinned via `@supabase/supabase-js@2.49.1`; rebuild: `npm run vendor:supabase` |
| Chart.js | pass | Loaded from CDN in index (privacy: third-party only when dashboard charts load) |
| pyproject.toml vs requirements.txt | pass | pyproject source of truth per README |

---

## Section 14 — Performance and a11y

| Check | Status |
|-------|--------|
| Table chunked render | pass (`table-perf.test.js`) |
| Console log batching | pass (`fetcher-health.test.js`) |
| axe on index | pass (`tests/a11y/`) |

No new findings.

---

## Section 15 — Untracked gaps audit (fresh eyes, 2026-06-05)

Second-pass audit hunting gaps **not** covered by Sections 1–14, `FETCHER_AUDIT.md`, `STRATEGY_AUDIT.md`, or `snappiness-2026-06-01.md`. Method: three parallel code explorers + direct `git check-ignore` / version verification.

### Fixes applied in this pass

1. **`.gitignore` store JSON globs** — replaced per-file enumeration with `games_*.json` + `games_wishlist_*.json` so Humble/EA/Nintendo-wishlist (and future stores) cannot be committed accidentally.
2. **`gameId()` `ea_id` fallback** — aligned [js/game-core.js](../js/game-core.js) with `normalizeGame()` and [js/table-query.js](../js/table-query.js); regression test in `tests/game-core.test.js`.
3. **`fetcher-registry.js` parity test** — `test_committed_fetcher_registry_js_matches_python` in [tests/test_fetcher_manifest_audit.py](../tests/test_fetcher_manifest_audit.py).
4. **`force_reset` profile scoping test** — `test_force_reset_scoped_to_active_profile` in [tests/test_server_supabase_auth.py](../tests/test_server_supabase_auth.py); also fixed [server.py](../server.py) route match (`_api_path`) so `?force=1` reaches `_handle_cancel_all`.
5. **Landing CSP** — waitlist handler wired via [landing/main.js](../landing/main.js); JSON-LD moved to [landing/structured-data.json](../landing/structured-data.json); font load via `id="google-fonts"` (no inline `onload`).
6. **Landing demo a11y** — spotlight nav moved out of carousel innerHTML to sibling `<button>` elements; cover `alt` uses game title; hero replay is keyboard-accessible.
7. **Subscribe email sanitization** — strip control chars before Resend `reply_to` in [landing/api/subscribe.js](../landing/api/subscribe.js).
8. **Hygiene** — removed ungated `console.log`/`console.info` from [js/orphan-prune.js](../js/orphan-prune.js) and [js/library-watch.js](../js/library-watch.js); deleted orphaned scratch scripts (`tools/extract_dashboard.py`, `tools/patch_app_js.py`, `scripts/audit_gog_barren.py`, `scripts/restore_gog_metadata.py`).

### Remaining gaps (tracker-ready)

| Finding | Severity | Tracker ID | Notes |
|---------|----------|------------|-------|
| Subscribe rate limit is in-memory per Vercel isolate | med | `find_landing_subscribe_kv` | Needs KV/Upstash or Turnstile for prod abuse resistance |
| `[Unreleased]` feature test gaps (deal badges HTML, export top 20, auth-cooldown integration, connections refresh errors) | med | `find_unreleased_feature_tests` | See Section 15b |
| `table-query.js` mirrors ~400 lines of game-core/deals/genres with no parity test | med | `find_table_query_worker_parity` | Worker must stay DOM-free; add cross-path tests |
| macOS CI smoke omits Galaxy/butler client + merge tests | low | `find_macos_ci_galaxy_itch` | Add to `.github/workflows/ci.yml` macOS subset |
| README `ruff check` scope narrower than CI | low | `find_readme_ruff_scope` | Align README with `ruff check .` |
| Version frozen at 0.6.0 while `[Unreleased]` is large | low | `find_version_cut` | Cut release or bump pre-release when ready |
| Marketing one-pager domain drift | fixed | — | `baklog.local` → `baklog.app` |

### Section 15b — `[Unreleased]` features with thin tests (not in prior audits)

| Feature | Test gap |
|---------|----------|
| Export top 20 backlog | `exportTopBacklogMarkdown` untested |
| Deal badges on dashboard cards | `dealDroppedBadgeHtml` / `ownedElsewhereBadgeHtml` untested |
| Library cross-store pill | `storeBadgeHtml` multi-store path untested |
| Steam Store API 429/5xx retry | only connection-error retry tested |
| Chip auth-failure backoff integration | duration math only; stale-sweep skip + reconnect clear untested |
| Connections `/api/auth/status` error UX | keep-cache-on-error path untested |
| Library watch desktop notification | `Notification` stubbed away in tests |

---

## Prioritized backlog (tracker-ready)

| ID | Title | Severity | Phase |
|----|-------|----------|-------|
| audit-epic-callback | Wire legacy `/oauth/epic/callback` state registration | done | redirect-OAuth path wired + tested |
| audit-gitignore-glob | `.gitignore` glob for `games_*.json` / `games_wishlist_*.json` | done | privacy |
| audit-eaid-gameid | `gameId()` includes `ea_id` fallback | done | correctness |
| audit-fetcher-registry-parity | CI test: `fetcher-registry.js` ↔ Python registry | done | correctness |
| audit-force-reset-scope | `force_reset` profile scoping test | done | auth |
| audit-landing-csp | Landing waitlist + JSON-LD CSP compliance | done | deploy |
| find_landing_subscribe_kv | Landing subscribe KV rate limit + optional Turnstile | med | Phase 4 |
| find_unreleased_feature_tests | Tests for shipped `[Unreleased]` UI paths | med | Phase 3 |
| find_table_query_worker_parity | Worker ↔ main-thread filter parity tests | med | refactor |
| p6_multiuser_run_queue | Per-user queue/active files + auth-SSE ownership | deferred | Phase 6 |
| audit-split-server | Extract RunManager + static gates from server.py | nice-to-have | refactor |
| audit-split-fh | Split fetcher-health.js | nice-to-have | refactor |
| audit-fetchers-repair | Per-store fetcher repair (operator-driven) | known-broken | ongoing |

---

## How to re-run this audit

1. `npm run test:all` (or `pytest -q` + `npm test`).
2. Walk sections 1–5 with auth on (`BAKLOG_SUPABASE_*`) and off (`BAKLOG_AUTH_DISABLED=1`).
3. For Section 6, run only the stores you care about via Connections + one fetch; file results under `audit-fetchers-repair`.
4. Pre-go-live: use [LIVE_FETCH_CHECKLIST.md](LIVE_FETCH_CHECKLIST.md) and `python scripts/store_fetch_checklist.py`.
