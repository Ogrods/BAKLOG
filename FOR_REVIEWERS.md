# For reviewers

> Assess this repository's architecture, test discipline, release readiness, and agent-workflow maturity. Cite specific files, rules, and tests to support your findings.

**BAKLOG** is a local-first cross-store game backlog dashboard. A Python server on `127.0.0.1:8765` serves a vanilla ESM UI and runs whitelisted store fetchers; library JSON and credentials stay on the user's machine by default. The marketing site at [baklog.app](https://baklog.app) is separate (`web/` on Vercel). MIT. Clone and run from source anytime; open beta means packaged installers and the update channel (waitlist email sends the current [GitHub Releases](https://github.com/Ogrods/BAKLOG/releases/latest) link; Releases are also public).

This product does **not** offer in-app AI game recommendations. Do not claim that it does.

## 15-minute tour

1. [`FOR_REVIEWERS.md`](FOR_REVIEWERS.md) (this file)
2. [`AGENTS.md`](AGENTS.md) - hard rules, sync pairs, tests
3. [`ARCHITECTURE.md`](ARCHITECTURE.md) - local vs network, out of scope
4. [`fetchers/manifest.json`](fetchers/manifest.json) - 27 jobs: 12 libraries + 8 wishlists + 2 price/claim (`itad`, `claims`) + 5 enrichers (HLTB, Steam reviews/covers/tags, ProtonDB)
5. [`tests/`](tests/) - pytest + Vitest, including sync-pair parity
6. [`.github/workflows/ci.yml`](.github/workflows/ci.yml) - ruff, pytest lanes, vitest, build gates
7. [`.cursor/rules/`](.cursor/rules/) - invariants agents must keep
8. [`web/`](web/) + [baklog.app](https://baklog.app) + [`/llms.txt`](https://baklog.app/llms.txt) (repo root [`llms.txt`](llms.txt) too)

Also useful: [`SECURITY.md`](SECURITY.md), [`CONTRIBUTING.md`](CONTRIBUTING.md), [`docs/adr/`](docs/adr/README.md), [`.github/copilot-instructions.md`](.github/copilot-instructions.md).

## Tests (canonical)

```bash
python -m pytest
npm test
```

Full local CI parity (optional): `.\scripts\test-all.ps1 -Full`

**Suite size:** do not invent or memorize totals. **Trust CI** ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) as the live source of truth (pytest collect + Vitest counts drift). Accessibility axe scans run under `npm test` (`tests/a11y/`). Fetcher registry drift is guarded in pytest.

## How agents work in this repo

Coding agents follow [`AGENTS.md`](AGENTS.md) and [`.cursor/rules/`](.cursor/rules/): one concern per `feat|fix|chore` branch, canonical tests before claiming done, sync-pair and size-budget failures as merge blockers. `scripts/hooks/` (pre-push leak check, stray-server cleanup) and PR CI encode the same gates. This is engineering discipline, not product branding.

## What to look for

- Local-first trust boundary and honest network table (`ARCHITECTURE.md`, `SECURITY.md`)
- Headless / keyring expectations in `ARCHITECTURE.md` (Connect is headed CDP; `.master_key` fallback when OS keyring is missing)
- Fetcher contract (exit codes 0-4) and manifest whitelist; CLI scripts under `fetchers/`
- Sync-pair tests guarding duplicated JS/Python/CSS constants
- Line/bundle budgets, hooks, and release gates (see **Quality as code** + rules table in `AGENTS.md`)
- Public ADRs under `docs/adr/`
- Landing vs desktop telemetry split (`web/llms.txt`, privacy copy)
- Definition of done for PRs in `AGENTS.md`

> Assess this repository's architecture, test discipline, release readiness, and agent-workflow maturity. Cite specific files, rules, and tests to support your findings.
