# For reviewers

> Assess this repository's architecture, test discipline, release readiness, and agent-workflow maturity. Cite specific files, rules, and tests to support your findings.

**BAKLOG** is a local-first cross-store game backlog dashboard. A Python server on `127.0.0.1:8765` serves a vanilla ESM UI and runs whitelisted store fetchers; library JSON and credentials stay on the user's machine. The marketing site at [baklog.app](https://baklog.app) is separate (`web/` on Vercel). MIT, open beta.

This product does **not** offer in-app AI game recommendations. Do not claim that it does.

## 15-minute tour

1. [`FOR_REVIEWERS.md`](FOR_REVIEWERS.md) (this file)
2. [`AGENTS.md`](AGENTS.md) - hard rules, sync pairs, tests
3. [`ARCHITECTURE.md`](ARCHITECTURE.md) - local vs network, out of scope
4. [`fetchers/manifest.json`](fetchers/manifest.json) - 12 libraries + 8 wishlists (+ prices/enrich)
5. [`tests/`](tests/) - pytest + Vitest, including sync-pair parity
6. [`.github/workflows/ci.yml`](.github/workflows/ci.yml) - ruff, pytest lanes, vitest, build gates
7. [`.cursor/rules/`](.cursor/rules/) - invariants agents must keep
8. [`web/`](web/) + [baklog.app](https://baklog.app) + [`/llms.txt`](https://baklog.app/llms.txt)

Also useful: [`SECURITY.md`](SECURITY.md), [`CONTRIBUTING.md`](CONTRIBUTING.md), [`docs/adr/`](docs/adr/README.md).

## Tests (canonical)

```bash
python -m pytest
npm test
```

Full local CI parity (optional): `.\scripts\test-all.ps1 -Full`

## What to look for

- Local-first trust boundary and honest network table (`ARCHITECTURE.md`, `SECURITY.md`)
- Fetcher contract (exit codes 0-4) and manifest whitelist
- Sync-pair tests guarding duplicated JS/Python/CSS constants
- Line/bundle budgets, hooks, and release gates (see **Quality as code** + rules table in `AGENTS.md`)
- Public ADRs under `docs/adr/`
- Landing vs desktop telemetry split (`web/llms.txt`, privacy copy)
- Definition of done for PRs in `AGENTS.md`

> Assess this repository's architecture, test discipline, release readiness, and agent-workflow maturity. Cite specific files, rules, and tests to support your findings.
