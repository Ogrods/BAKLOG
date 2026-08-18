# BAKLOG — agent brief

**BAKLOG** is a local-only cross-store game backlog dashboard. Library JSON, credentials, and personal data stay on the user's machine — nothing is hosted for end users except the public marketing landing (`landing/` on Vercel).

## Architecture (one screen)

| Layer | Entry | Notes |
|-------|-------|-------|
| **Server** | `server.py` | stdlib `ThreadingHTTPServer` on `127.0.0.1:8765`; serves static app + `/api/*` JSON + SSE streams |
| **Auth** | `auth/` | AES-GCM secrets + OS keyring; CDP browser sign-in (`cdp_browser.py`, `runner.py`) |
| **Fetchers** | `fetch_*.py`, `fetchers/manifest.json` | Whitelisted subprocess scripts → profile-scoped `games_*.json` |
| **Frontend** | `index.html`, `js/app.js` | Vanilla ESM modules; optional esbuild `dist/` build |
| **Landing** | `landing/` | Static marketing site + Vercel serverless (`api/subscribe.js`, `api/report.js`). Attended SEO playbook: `.cursor/rules/seo-operator.mdc` |
| **Profiles** | `profiles/<id>/` | Per-profile catalogs, `data/personal.json`, `cache/auth/` |

Deep reference (maintainer clone only): `docs/ARCHITECTURE.md` in the private `baklog-internal` repo.

## Hard rules

1. **Python on Windows** — use `.\.venv\Scripts\python.exe`, not Store `python`.
2. **Never commit to public repo** — `marketing/`, `admin/`, `docs/`, `tracker.html`, personal data (`games_*.json`, `data/`, `profiles/`, `.env`). See `.gitignore`.
3. **Fetcher contract** — each script exposes `main() -> int`. Exit codes: `0` ok, `1` error, `2` refused empty, `3` refused drift, `4` auth failure (`fetchers/_progress.py`).
4. **Mutating localhost API** — send `X-BAKLOG-Local: 1` from the app/admin console.
5. **Admin console** — only when `BAKLOG_ADMIN=1`; routes under `/api/internal/*`.
6. **Keep sync pairs aligned** — `js/store-brand-colors.js` ↔ `app.css --brand-*`; `js/theme.js` ↔ theme CSS; `landing/marquee-speed.js` ↔ `js/marquee-speed.js`; `js/fetcher-registry.js` ↔ `fetchers/registry.py` (generated — `python -c "from fetchers.registry import export_js_registry; export_js_registry()"`); `js/library-noise.js` ↔ `shared/library_noise.py`; `js/claim-card.js` `stripClaimTitleDecorations` ↔ `shared/steam_match.py` `strip_giveaway_decorations`; `js/claim-card.js` `sanitizeBlurb` ↔ `build_free_claims.py` `_clean_blurb`; `js/claim-card.js` `CLAIM_SOURCE_RANK` ↔ `shared/free_claims_sources.py` `SOURCE_PRECEDENCE`; `js/claim-sort.js` `sortClaimsItems` / `SORT_FNS.newest` ↔ `js/claim-card.js` `sortClaims` ↔ `admin/claims-workspace.js` re-export; `admin/claims-workspace.js` `normTitleKey` / `gameMatchKeys` ↔ `shared/free_claims_sources.py` `norm_title` / `claim_match_keys` (admin `coverLookupKey` is intentionally looser for DUPE stamps only); `js/sponsored-deals.js` `HOUSE_BANNER_FEATURES` / `PRO_PROMO` ↔ `landing/index.html` trust pillars + paid-tier copy; `js/sponsored-deals.js` `AD_LOCATIONS` / `LOCATION_GROUPS` / `LOCATION_CAPACITY` ↔ `admin/admin.js` (and `shared/sponsors_validate.py` `SPONSOR_AD_LOCATIONS`, `scripts/migrate_sponsors_v2.py`); admin Metrics catalog + `metricKeyForLabel` ↔ `METRIC_TIPS` keys in `js/metric-tips.js`. Partial lists in `.cursor/rules/frontend.mdc` and `landing.mdc` — **this rule is the canonical full list**.
7. **Scope discipline** — new user-visible surfaces must state which budget they fit (module line cap, bundle entry/CSS ceiling, or `server.py` line cap) and prefer lazy/flagged/admin-gated delivery (`?debug=1`, `BAKLOG_ADMIN=1`) over always-on code. Extend registries (`fetchers/manifest.json`, `METRIC_TIPS`, `BAKLOG_EVENT_REGISTRY`) instead of growing monolith modules (`fetcher-health.js`, `connections.js`, `table-ui.js`).
8. **No em dashes or AI tells in front-facing copy** — never use `—` (em dash, U+2014) in any user-visible string: app UI (`index.html`, rendered `js/*.js` strings, `app.css` `content:`), landing site (`landing/`), marketing copy, and rendered data feeds (`curated/sponsors.json`, `landing/sponsors.json`, `fetchers/manifest.json` notes). Use a spaced hyphen (` - `) or rephrase. Also avoid LLM-flavored marketing: rule-of-three triads as default rhythm; contrast frames (`not just X, but Y`, `it's not X, it's Y`, `X tells you… BAKLOG tells you…`); hype verbs (`unlock`, `elevate`, `supercharge`, `leverage`, `seamless`, `robust`, `delve`, `game-changer`, `secret sauce`); empty intensifiers (`finally`, `100%`, `radically`); abstract positioning (`decision layer`, `concierge`) when a concrete noun works; and repeating the same claim verbatim across hero, features, FAQ, and ads - vary or cut. This applies only to copy users read; code comments, docstrings, and server/console diagnostics are exempt. Third-party game titles/blurbs in claim feeds are not our copy and stay verbatim.

## Profile isolation

- **Active profile** — `profiles/index.json` owns the menu selection; `server.py` pops its own `BAKLOG_PROFILE` at boot so the index is canonical for the dashboard.
- **`BAKLOG_PROFILE` env** — overrides the index for CLI/subprocess fetchers; bypasses the per-profile PIN gate (PIN guards switch-in via the menu, not data at rest).
- **New profiles** — `seed_new_profile_auth_defaults` opts out all `kind=local` providers (Amazon, GOG Galaxy, itch local) until explicit Connect on that profile.
- **Switch safety** — profile switch cancels in-flight fetchers, resets secrets cache, rebinds run paths, and blocks switch while a browser sign-in is active.

## Ads & banners — how a change reaches the app

Two **separate** systems; mixing them up is why banner edits "don't show". Full guide: `.cursor/rules/frontend.mdc` → "Banners & ads".

- **Feed-driven** (`house-*` deal slots, dash-spotlight Pro slides, paid `ad-*`): from `sponsors.json`. App resolution order (first non-empty wins): local profile `/sponsors.json` → **hosted `baklog.app/sponsors.json`** → bundled `curated/sponsors.json`. The **hosted feed wins on any online machine**, so editing `curated/sponsors.json` alone changes nothing. To ship: edit `landing/sponsors.json` (mirror `curated/`), keep the rule-6 sponsor sync pairs aligned (and add to `PRO_PROMO_SPONSOR_IDS` if it should open the Pro tab), commit, push, let Vercel redeploy, then **verify with `Invoke-WebRequest https://baklog.app/sponsors.json`**.
- **Hardcoded JS** (dashboard `PRO_PROMO` banner, wishlist house banner, Connections background-refresh note via `bgRefreshPlanNote()` in `js/connections.js`): from `js/` source only. Edit + reload (dev raw ESM is `no-store`); run `npm run build` if serving built `dist/`. The Connections note renders only on the Connections tab for non‑Pro sessions.

## Weight guardrails (CI)

- `npm run check:module-size` — any `js/*.js` over **3800** lines fails (`table-query.worker.js` exempt).
- `npm run check:bundle-size` — critical-path `dist/` entry JS + CSS ceilings in `size-budget.json`.
- `npm run lint` — ESLint weight rules (`max-lines`, `complexity`, `import/no-cycle`; warnings for now).
- `pytest tests/test_repo_size_budgets.py` — `server.py` capped at **4320** lines; `scripts/git_tree.py` at **720**.

Refresh bundle budget after intentional growth: `npm run build && node scripts/check-bundle-size.mjs --write`.

**Full local CI parity:** `.\scripts\test-all.ps1 -Full` runs ruff → pytest → vitest → **test:perf** → check:module-size → lint → vendor:supabase → build → check:bundle-size → check:dist-integrity → `scripts/audit_free_surface_data.py --fail-on high` → **release_smoke** (Steam store contracts; same gate as `release.yml` before tagging).

**Runtime perf:** `npm run test:perf` (Vitest micro-benchmarks vs `perf-budget.json`); `.\scripts\start-perf-server.ps1` or `node scripts/perf-audit.mjs` for Playwright boot/tab timing (requires built server + `BAKLOG_PROFILE=perf`). Opt-in marks: `?perf=1` → `window.__baklogBootPerf`, `__baklogPerf`, `__baklogChartPerf`.

## Auth gating (layers)

- **CSRF** — mutating requests require `X-BAKLOG-Local: 1` (the app and admin console send it). When Supabase auth is on, a valid bearer may also authorize mutations; Origin/Referer alone is not enough.
- **Supabase JWT** — when `BAKLOG_SUPABASE_URL` + anon key set; all `/api/*` except `/api/config` require bearer token.
- **BAKLOG_ADMIN** — exposes `/admin/` and `/api/internal/*` without Supabase.

## Tests & dev

```powershell
.\.venv\Scripts\python.exe -m pytest          # Python (skips integration by default)
npm test                                       # Vitest (JS)
$env:BAKLOG_ADMIN="1"; .\.venv\Scripts\python.exe server.py   # dev + admin
.\.venv\Scripts\python.exe scripts\stop_baklog.py             # stop strays (+ --dry-run / --dedupe)
```

Run the dev server in **one** dedicated terminal and reuse it — `server.py` is a
blocking `serve_forever()` loop. Strays are now contained by three layers so they
no longer pile up (Cursor's "N agents with open processes" at quit):

- **Idle self-exit** — a watchdog (`shared/idle_watchdog.py`) quits the dev server
  after 30 min with no client contact (a server with an open dashboard tab is
  polled every ~30s, so it never idles out; an agent server with no browser
  self-exits). Tune with `BAKLOG_IDLE_SHUTDOWN_MINUTES` (`0` disables); off for
  frozen builds unless set. It never interrupts an in-flight fetch or sign-in.
- **Boot self-heal** — every start clears a dead-pid `.baklog_server.pid` and
  reclaims the port from its own orphan (`shared/dev_server_pids.reclaim_or_exit`).
- **Session-end dedupe** — the Cursor stop hook
  (`scripts/hooks/cleanup-baklog-strays.py` → `stop_baklog.py --dedupe`) keeps the
  one live server and kills extra server/tray strays when an agent turn ends.

Manual cleanup after a messy session: `stop_baklog.py` (graceful `POST
/api/shutdown`, then force-kills any server/tray still on port 8765 and clears
`.baklog_server.pid`); `--dedupe` keeps the live server and removes only extras.

## Parallel agents (git hygiene)

When multiple Cursor agents work at once, **one agent = one git worktree = one single-purpose branch**. Never share an uncommitted working tree across agents.

**Branch naming** — always prefix: `feat/`, `fix/`, or `chore/`. Ban bare names like `pro-debug-url`. One concern per branch; do not stack unrelated commits (e.g. Pro funnel + spotlight discovery + dev flags on one branch).

**Worktrees** — give each concurrent agent its own folder:

```powershell
.\scripts\new-worktree.ps1 feat/pro                 # -> ..\baklog-pro on feat/pro
.\scripts\new-worktree.ps1 feat/spotlight-discovery # rejects bare names; feat/|fix/|chore/ only
git worktree list                                   # dashboard of who is where
.\scripts\close-worktree.ps1 feat/pro               # after squash-merge: remove + delete local/remote + prune
```

The helpers enforce the branch-naming scheme and junction `.venv` + `node_modules` into the new folder so it is usable immediately. Raw equivalent: `git worktree add ..\baklog-pro feat/pro`.

**Merge hygiene** — squash-merge PRs to `main`, then delete the local branch and `git push origin --delete <branch>`. Run `git fetch --prune` after cleanup. Tag or bundle before destructive branch deletes (`git tag backup/<branch>-YYYY-MM-DD <branch>`; `git bundle create ..\baklog-backups\pre-reset.bundle --all`).

**Tracker handoff** — edit `..\baklog-internal\tracker.html` directly when the sibling clone exists, then `.\scripts\sync-internal-repo.ps1 -Push`. Fallback: `.cursor/tracker-pending-<slug>.md` (or legacy `tracker-update-pending-<slug>.md` in repo root — also gitignored); backstop: `/apply-tracker-pending`. Do not create `PROGRESS.md`.

## Progress tracker

Canonical progress lives in **`..\baklog-internal\tracker.html`** (private sibling clone, gitignored in public). On completing a meaningful task, update the relevant `PHASES` / findings entry with `[DONE]` or `[RESOLVED]` and a dated note, then push via `sync-internal-repo.ps1 -Push`. If the internal clone is unavailable or editing is blocked, write `.cursor/tracker-pending-<slug>.md` and run `/apply-tracker-pending` later — do not create a separate `PROGRESS.md`. See `docs/WORKFLOW.md` and `.cursor/rules/internal-workflow.mdc`.

## Maintainer docs (private repo)

Marketing, admin console, workflow commands, and internal Cursor rules sync to **`Ogrods/baklog-internal`** via `scripts/sync-internal-repo.ps1`. Public push hook: `git config core.hooksPath scripts/hooks`.
