# GitHub Copilot / PR agents

**Source of truth:** [`AGENTS.md`](../AGENTS.md). Read it before changing code. Companion stubs: [`CLAUDE.md`](../CLAUDE.md), [`FOR_REVIEWERS.md`](../FOR_REVIEWERS.md), root [`llms.txt`](../llms.txt).

## Canonical tests

```bash
python -m pytest
npm test
```

Optional full gate: `.\scripts\test-all.ps1 -Full`. Trust `.github/workflows/ci.yml` for live suite status.

## Key invariants

- Local-first: credentials and library JSON stay on the machine; mutating localhost APIs need `X-BAKLOG-Local: 1`.
- Fetcher exit codes 0-4 (`fetchers/_progress.py`); only `fetchers/manifest.json` keys may run.
- Keep AGENTS.md rule-6 sync pairs aligned; extend registries instead of growing monoliths.
- No em dashes (U+2014) or LLM-flavored marketing in user-facing copy.
- Do **not** claim BAKLOG has in-app AI game recommendations.

## Definition of done

Branch `feat/` / `fix/` / `chore/`, one concern, canonical tests green, sync pairs updated with tests when touched, no secrets/personal data, PR template filled. See **Definition of done** in `AGENTS.md`.
