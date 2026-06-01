# AGENTS.md

## Cursor Cloud specific instructions

### Product overview

BAKLOG is a **local-only** cross-store game backlog dashboard. One Python dev server (`server.py`) serves the static UI plus REST/SSE APIs for personal data, fetcher orchestration, and store sign-in. There is no Docker, database, or monorepo.

### Required services

| Service | Command | Port |
|---------|---------|------|
| BAKLOG dev server | `python3 server.py` | `8765` (binds `127.0.0.1`) |

Optional read-only mode: `python3 -m http.server 8080` (no personal-data API or fetcher triggers).

### Dependency install

See `README.md` and `.github/workflows/ci.yml`. Standard path:

```bash
pip install -e ".[dev]"
npm ci
```

Python **3.11+** is required (`pyproject.toml`). Node **20+** is used in CI for Vitest.

If `pytest`, `ruff`, or `playwright` are not found after pip install, add `~/.local/bin` to `PATH` (user-site scripts on this VM).

### Lint / test / run

| Task | Command |
|------|---------|
| Python tests | `pytest -q` |
| Python lint | `ruff check .` (advisory in CI; some existing debt) |
| JS tests | `npm test` |
| Dev server | `python3 server.py` → http://127.0.0.1:8765 |

### Sample library data

Generated `games_*.json` files are gitignored. A fresh clone has an empty dashboard until fetchers run or fixture JSON is placed at the repo root. For UI smoke tests without store credentials, a minimal `games_steam.json` with a `games` array is enough (see `fetch_games.py` output shape).

### Optional: Playwright / Connections tab

Store sign-in via the Connections tab needs a one-time browser install:

```bash
playwright install chromium
```

Not required for dashboard browsing, pytest, or vitest.

### Gotchas

- ES modules require HTTP — do not open `index.html` via `file://`; use `server.py`.
- `data/personal.json` and `cache/` are created at runtime and gitignored.
- Live fetchers need credentials in `.env` (copy from `.env.example`) or the Connections tab; ITAD/Steam fetch failures without credentials are expected.
