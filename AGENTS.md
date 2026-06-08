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
6. **Keep sync pairs aligned** — `js/store-brand-colors.js` ↔ `app.css --brand-*`; `js/theme.js` ↔ theme CSS; `landing/marquee-speed.js` ↔ `js/marquee-speed.js`; `js/claimable.js` `stripClaimTitleDecorations` ↔ `shared/steam_match.py` `strip_giveaway_decorations`.

## Auth gating (layers)

- **CSRF** — `X-BAKLOG-Local: 1` or valid localhost Origin/Referer for mutating requests.
- **Supabase JWT** — when `BAKLOG_SUPABASE_URL` + anon key set; all `/api/*` except `/api/config` require bearer token.
- **BAKLOG_ADMIN** — exposes `/admin/` and `/api/internal/*` without Supabase.

## Tests & dev

```powershell
.\.venv\Scripts\python.exe -m pytest          # Python (skips integration by default)
npm test                                       # Vitest (JS)
$env:BAKLOG_ADMIN="1"; .\.venv\Scripts\python.exe server.py   # dev + admin
```

## Progress tracker

Canonical progress lives in **`tracker.html`** (private, gitignored). On completing a meaningful task, update the relevant `PHASES` / findings entry with `[DONE]` or `[RESOLVED]` and a dated note — do not create a separate `PROGRESS.md`. See `docs/WORKFLOW.md` and `.cursor/rules/internal-workflow.mdc` in the maintainer clone.

## Maintainer docs (private repo)

Marketing, admin console, workflow commands, and internal Cursor rules sync to **`Ogrods/baklog-internal`** via `scripts/sync-internal-repo.ps1`. Public push hook: `git config core.hooksPath scripts/hooks`.
