# CLAUDE.md

**Source of truth:** [`AGENTS.md`](AGENTS.md). Read that file first and follow it. This stub exists so Claude Code and other non-Cursor agents get the same boundaries without a second conflicting brief.

## Non-negotiables

1. Windows Python: `.\.venv\Scripts\python.exe` (not Store `python`).
2. Never commit personal data, `profiles/`, `games_*.json`, `.env`, or gitignored maintainer paths (`marketing/`, `admin/`, private `docs/` deep notes).
3. Fetcher `main() -> int` exit codes: `0` ok, `1` error, `2` empty refused, `3` drift refused, `4` auth (`fetchers/_progress.py`).
4. Mutating localhost API: `X-BAKLOG-Local: 1`.
5. Keep AGENTS.md rule-6 sync pairs aligned; extend registries instead of growing monoliths.
6. No em dashes (U+2014) or LLM-flavored marketing in user-facing copy.
7. Do **not** claim BAKLOG has in-app AI game recommendations.

## Architecture boundaries

| Layer | Entry |
|-------|-------|
| Server | `server.py` on `127.0.0.1:8765` |
| Auth | `auth/` (AES-GCM + CDP) |
| Fetchers | `fetchers/fetch_*.py` + `enrichers/` + `fetchers/manifest.json` |
| Frontend | `index.html`, `js/` |
| Landing / Pro mirror | `web/` (Vercel) |
| Profiles | `profiles/<id>/` (local, gitignored at runtime) |

Public overview: [`ARCHITECTURE.md`](ARCHITECTURE.md). Reviewer tour: [`FOR_REVIEWERS.md`](FOR_REVIEWERS.md).

## Tests (canonical)

```bash
python -m pytest
npm test
```

Full local CI parity: `.\scripts\test-all.ps1 -Full`  
Landing SEO: `npm run check:landing-seo`

## Definition of done (PRs)

Branch `feat/` / `fix/` / `chore/`, one concern, canonical tests green, sync pairs updated with tests when touched, no secrets/personal data, PR template filled. See **Definition of done** in [`AGENTS.md`](AGENTS.md).
