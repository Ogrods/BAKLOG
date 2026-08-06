# Contributing to BAKLOG

Thanks for your interest. BAKLOG is a local-first cross-store game backlog
dashboard: the app, fetchers, auth, and dashboard are MIT-licensed and live in
this repo. Your library JSON and credentials never leave your machine.

This guide covers how to set up, make a change, and open a pull request.

## Development setup

Requirements: Python 3.11 and Node.js 22+.

```bash
# Python (use a virtualenv; on Windows use .\.venv\Scripts\python.exe)
python -m venv .venv
pip install -e ".[dev]"

# JavaScript
npm ci
```

Run the dev server (the dashboard is vanilla ESM, no build step needed for dev):

```bash
python server.py            # http://127.0.0.1:8765
```

On Windows, always use the venv interpreter (`.\.venv\Scripts\python.exe`), not
the Microsoft Store `python` shim.

## Tests

Run the suites before opening a PR:

```bash
python -m pytest            # Python (skips integration by default)
npm test                    # JavaScript (Vitest)
```

Full local CI parity (ruff, pytest, vitest, size budgets, lint, build, bundle
checks):

```powershell
.\scripts\test-all.ps1 -Full
```

## Branches

One concern per branch. Always prefix the branch name:

- `feat/` - a new feature
- `fix/` - a bug fix
- `chore/` - tooling, docs, refactors, housekeeping

Bare names (e.g. `my-changes`) are rejected by the worktree helpers. Do not
stack unrelated work on one branch.

## Commits

- Write clear, imperative subjects (e.g. "Add EA wishlist fetcher").
- Keep each commit focused; avoid one mega-commit that mixes unrelated changes.
- Conventional Commit prefixes are welcome but not required.

## Pull requests

1. Branch off `main` with a `feat/` / `fix/` / `chore/` name.
2. Make the change and keep commits focused.
3. Run `python -m pytest` and `npm test` (or `test-all.ps1 -Full`).
4. Open the PR and fill in the template.

PRs are squash-merged to `main`, so the branch collapses to one clean commit.

## Releases (maintainers)

Releases are immutable and built by CI, not hand-uploaded. To cut one:

1. Bump the version in `pyproject.toml`, `package.json`, and the `index.html`
   meta tag (all three must match).
2. Commit, then tag and push:

   ```bash
   git tag v0.8.17
   git push origin v0.8.17
   ```

The `release` workflow builds the Windows bundle on a clean runner, attaches a
SHA-256 and a signed build-provenance attestation, and publishes the GitHub
Release. The build refuses to run if the tag does not match the version in
`pyproject.toml`.

Never move or re-point a published tag. Cut a new patch tag instead.

## Local API note

Mutating requests to the local server require the `X-BAKLOG-Local: 1` header.
The app and admin console send this automatically. A localhost Origin/Referer
alone is not enough. When Supabase auth is enabled, a valid bearer token may
also authorize mutations.

## Reporting security issues

Do not open a public issue for security reports. See
[SECURITY.md](SECURITY.md) for how to report privately.

## Architecture and review notes

- **[ARCHITECTURE.md](ARCHITECTURE.md)** - repo layout, runtime diagram, network
  boundaries, Pro licensing, and why `server.py` is still large.
- **Telemetry** - no telemetry by default; opt-in aggregate metrics only (`shareAnonStats`).
- **Hosted feeds** - public `sponsors.json` / `free-claims.json` on baklog.app when
  online; library data is not uploaded.
- **Store ToS** - several fetchers replay your web session; see [SECURITY.md](SECURITY.md).
- **CI scope** - default pytest skips `@integration` and `@release_smoke`; run
  `pytest -m integration` locally for CDP/browser flows.
