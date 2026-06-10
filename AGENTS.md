# BAKLOG — agent brief

**BAKLOG** is a local-only cross-store game backlog dashboard. Library JSON, credentials, and personal data stay on the user's machine — nothing is hosted for end users except the public marketing landing (`landing/` on Vercel).

## Architecture (one screen)

| Layer | Entry | Notes |
|-------|-------|-------|
| **Server** | `server.py` | stdlib `ThreadingHTTPServer` on `127.0.0.1:8765`; serves static app + `/api/*` JSON + SSE streams |
| **Auth** | `auth/` | AES-GCM secrets + OS keyring; CDP browser sign-in (`cdp_browser.py`, `runner.py`) |
| **Fetchers** | `fetch_*.py`, `fetchers/manifest.json` | Whitelisted subprocess scripts → profile-scoped `games_*.json` |
| **Frontend** | `index.html`, `js/app.js` | Vanilla ESM modules; optional esbuild `dist/` build |
| **Landing** | `landing/` | Static marketing site + Vercel serverless (`api/subscribe.js`, `api/report.js`) |
| **Profiles** | `profiles/<id>/` | Per-profile catalogs, `data/personal.json`, `cache/auth/` |

Deep reference (maintainer clone only): `docs/ARCHITECTURE.md` in the private `baklog-internal` repo.

## Hard rules

1. **Python on Windows** — use `.\.venv\Scripts\python.exe`, not Store `python`.
2. **Never commit to public repo** — `marketing/`, `admin/`, `docs/`, `tracker.html`, personal data (`games_*.json`, `data/`, `profiles/`, `.env`). See `.gitignore`.
3. **Fetcher contract** — each script exposes `main() -> int`. Exit codes: `0` ok, `1` error, `2` refused empty, `3` refused drift, `4` auth failure (`fetchers/_progress.py`).
4. **Mutating localhost API** — send `X-BAKLOG-Local: 1` from the app/admin console.
5. **Admin console** — only when `BAKLOG_ADMIN=1`; routes under `/api/internal/*`.
6. **Keep sync pairs aligned** — `js/store-brand-colors.js` ↔ `app.css --brand-*`; `js/theme.js` ↔ theme CSS; `landing/marquee-speed.js` ↔ `js/marquee-speed.js`; `js/claim-card.js` `stripClaimTitleDecorations` ↔ `shared/steam_match.py` `strip_giveaway_decorations`; `js/claim-card.js` `sanitizeBlurb` ↔ `build_free_claims.py` `_clean_blurb`; `js/claim-card.js` `CLAIM_SOURCE_RANK` ↔ `shared/free_claims_sources.py` `SOURCE_PRECEDENCE`; `admin/claims-workspace.js` `normTitleKey` / `gameMatchKeys` ↔ `shared/free_claims_sources.py` `norm_title` / `claim_match_keys` (admin `coverLookupKey` is intentionally looser for DUPE stamps only); `js/sponsored-deals.js` `HOUSE_BANNER_FEATURES` / `PRO_PROMO` ↔ `landing/index.html` trust pillars + paid-tier copy; `js/sponsored-deals.js` `AD_LOCATIONS` / `LOCATION_GROUPS` / `LOCATION_CAPACITY` ↔ `admin/admin.js` (and `server.py` `SPONSOR_AD_LOCATIONS`); admin Metrics catalog + `metricKeyForLabel` ↔ `METRIC_TIPS` keys in `js/metric-tips.js`.
7. **Scope discipline** — new user-visible surfaces must state which budget they fit (module line cap, bundle entry/CSS ceiling, or `server.py` line cap) and prefer lazy/flagged/admin-gated delivery (`?debug=1`, `BAKLOG_ADMIN=1`) over always-on code. Extend registries (`fetchers/manifest.json`, `METRIC_TIPS`, `BAKLOG_EVENT_REGISTRY`) instead of growing monolith modules (`fetcher-health.js`, `connections.js`, `table-ui.js`).

## Weight guardrails (CI)

- `npm run check:module-size` — any `js/*.js` over **3800** lines fails (ratchet down after splits).
- `npm run check:bundle-size` — critical-path `dist/` entry JS + CSS ceilings in `size-budget.json`.
- `npm run lint` — ESLint weight rules (`max-lines`, `complexity`, `import/no-cycle`; warnings for now).
- `pytest tests/test_repo_size_budgets.py` — `server.py` capped at **4530** lines.

Refresh bundle budget after intentional growth: `npm run build && node scripts/check-bundle-size.mjs --write`.

## Auth gating (layers)

- **CSRF** — `X-BAKLOG-Local: 1` or valid localhost Origin/Referer for mutating requests.
- **Supabase JWT** — when `BAKLOG_SUPABASE_URL` + anon key set; all `/api/*` except `/api/config` require bearer token.
- **BAKLOG_ADMIN** — exposes `/admin/` and `/api/internal/*` without Supabase.

## Tests & dev

```powershell
.\.venv\Scripts\python.exe -m pytest          # Python (skips integration by default)
npm test                                       # Vitest (JS)
$env:BAKLOG_ADMIN="1"; .\.venv\Scripts\python.exe server.py   # dev + admin
.\.venv\Scripts\python.exe scripts\stop_baklog.py             # stop strays (+ --dry-run)
```

Run the dev server in **one** dedicated terminal and reuse it — `server.py` is a
blocking `serve_forever()` loop, so spawning a fresh `python server.py` per task
leaves the old ones running and they pile up (Cursor's "N agents with open
processes" at quit). To clean up after a messy session: `stop_baklog.py` (graceful
`POST /api/shutdown`, then force-kills any server/tray still on port 8765 and
clears `.baklog_server.pid`).

## Progress tracker

Canonical progress lives in **`tracker.html`** (private, gitignored). On completing a meaningful task, update the relevant `PHASES` / findings entry with `[DONE]` or `[RESOLVED]` and a dated note — do not create a separate `PROGRESS.md`. See `docs/WORKFLOW.md` and `.cursor/rules/internal-workflow.mdc` in the maintainer clone.

## Maintainer docs (private repo)

Marketing, admin console, workflow commands, and internal Cursor rules sync to **`Ogrods/baklog-internal`** via `scripts/sync-internal-repo.ps1`. Public push hook: `git config core.hooksPath scripts/hooks`.
