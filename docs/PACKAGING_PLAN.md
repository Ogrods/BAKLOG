# BAKLOG packaging plan — Windows executable (PyInstaller)

**Status:** Plan (not shipped)  
**Tracker:** `p4_packaging` · Beta tab → setup link  
**Decision:** Ship a **frozen Windows `.exe`** for beta testers (no Python install). Keep local-first architecture; Chrome/Edge still required for Connect.

---

## Goal

Beta testers should:

1. Download **one artifact** (eventually `BAKLOG.exe`, or interim zip — see phases below).
2. Double-click to start the local server.
3. Browser opens to `http://127.0.0.1:8765`.
4. Connect stores → Refresh → library appears.

The invite emails' `[setup link]` should point at a **GitHub Release** (or baklog.app/download when ready), not the README clone flow.

---

## What exists today

| Artifact | Python required? | Notes |
|----------|------------------|-------|
| Clone + `pip install` + `python server.py` | Yes | README flow; too much friction for general beta. |
| `scripts/build_installer.ps1` | **Yes** | Copies repo to `dist/baklog/` + `Start BAKLOG.bat`. Good **interim** zip for technical friends; not the end state. |
| PyInstaller `.exe` | No | **Target.** Not implemented yet. |

---

## Hard constraint: fetcher subprocess model

`server.py` launches every store fetch as a **child Python process**:

```python
def _argv(*parts: str) -> list[str]:
    return [_python_executable(), *parts]
```

Each manifest entry resolves to e.g. `python C:\...\fetch_games.py`. In a frozen build there is no `python.exe` and scripts live inside the bundle. **A frozen server that does not fix this will load the UI but every fetch will fail.**

### Required pattern: re-invoke self

When `sys.frozen` is true:

```text
BAKLOG.exe                          → server (main)
BAKLOG.exe --run-fetcher steam …    → dispatch to fetch_games.main()
BAKLOG.exe --run-fetcher gog …      → dispatch to fetch_gog.main()
```

Implementation sketch:

1. Early in `server.py` `__main__` (before heavy imports if possible): if `sys.argv[1] == "--run-fetcher"`, call `baklog_fetcher_dispatch.run(sys.argv[2:])` and exit.
2. `_argv()` when frozen: `[sys.executable, "--run-fetcher", <manifest_key>, *extra_args]` instead of `[python, fetch_script.py, ...]`.
3. `baklog_fetcher_dispatch.py`: map manifest `key` → import module → `sys.argv = reconstructed` → `raise SystemExit(module.main())`.

Prefer **import + `main()`** over `runpy.run_path` so PyInstaller hiddenimports stay reliable.

---

## Hard constraint: two roots (bundle vs data)

Today many modules define their own `ROOT = Path(__file__).resolve().parents[1]`:

- `server.py`
- `shared/profile_paths.py` (drives all catalog / profile / cache paths)
- `auth/manager.py`, `auth/secrets.py`, `auth/bundle.py`
- `fetchers/registry.py`
- `shared/safe_write.py`

When frozen:

| Path | Purpose |
|------|---------|
| **Bundle root** (`sys._MEIPASS`) | Read-only: `index.html`, `js/`, `css`, `fetchers/manifest.json`, `assets/`, static files served by HTTP handler |
| **Data root** (next to `BAKLOG.exe`) | Writable: `profiles/`, `games_*.json`, `data/`, `cache/`, `_runs.json`, `.env` import |

If data lives inside `_MEIPASS`, user libraries **vanish on every launch** (temp extract dir).

### New module: `shared/install_paths.py`

Single source of truth:

```python
def is_frozen() -> bool: ...
def bundle_root() -> Path: ...   # _MEIPASS or repo root in dev
def data_root() -> Path: ...     # dirname(sys.executable) when frozen; else bundle_root()
def static_root() -> Path: ...   # bundle_root() — HTTP server serves from here
```

Override for dev/testing: `BAKLOG_DATA_DIR`.

Migrate `shared/profile_paths.ROOT` → `data_root()` and `server.ROOT` split into `static_root()` / `data_root()` as appropriate.

HTTP handler: `partial(Handler, directory=str(static_root()))`.

Fetcher `cwd`: `str(data_root())` or `str(bundle_root())` — only matters for relative paths; prefer absolute argv via dispatch.

---

## PyInstaller spec (Windows v1)

**New files:**

- `packaging/baklog.spec` — PyInstaller spec
- `packaging/build_windows.ps1` — venv + pyinstaller one-liner
- `baklog_fetcher_dispatch.py` — `--run-fetcher` entry (or inline in `server.py`)

**Entry point:** `server.py` (console app for v1 so testers see errors; windowed `.exe` later).

**Datas (bundle, not exhaustive):**

- `index.html`, `tracker.html`, `app.css`, `tailwind.css`, `favicon.svg`
- `js/`, `assets/`, `vendor/`
- `fetchers/manifest.json`, `fetchers/registry` package data
- `auth/` templates if any on disk

**Hiddenimports (audit as build fails):**

- All `fetch_*.py` modules
- `auth`, `fetchers`, `shared`, `enrichers`
- `keyring.backends.*`, `cryptography`, store clients (`steam_client`, `epic_client`, …)
- `psnawp`, `howlongtobeatpy`

**Excludes:** `tests/`, `landing/`, `marketing/`, `node_modules/`, `.venv/`

**Output:** `dist/BAKLOG/BAKLOG.exe` (onedir recommended for v1 — faster debug, smaller incremental updates) or onefile (simpler download, slower cold start).

---

## Phased delivery

### Phase 0 — Interim (can ship this week)

1. Run `scripts/build_installer.ps1`.
2. Zip `dist/baklog/` → GitHub Release `v0.6.0-beta.1`.
3. `docs/BETA_SETUP.md` documents: install Python 3.11+, unzip, run `Start BAKLOG.bat`.
4. Beta invite `[setup link]` → release page.

**Pros:** No code changes. **Cons:** Still requires Python — OK for first 5–10 technical testers only.

### Phase 1 — Frozen MVP (target for real beta)

1. `shared/install_paths.py` + migrate ROOT usages.
2. `--run-fetcher` dispatch + frozen `_argv()`.
3. `packaging/baklog.spec` + manual test on Windows.
4. Verify: server boots, static UI loads, **Steam fetch** works end-to-end, Connect opens Chrome.
5. GitHub Release `BAKLOG-win64.zip` (onedir folder + optional `Start BAKLOG.bat` that runs `BAKLOG.exe`).
6. Update `docs/BETA_SETUP.md` and tracker Beta emails: no Python step.

### Phase 2 — Polish

- Code signing (reduce SmartScreen warnings).
- GitHub Actions `workflow_dispatch` build on `windows-latest`.
- Auto-open browser on start (`webbrowser.open`).
- Desktop shortcut / optional NSIS installer wrapper.
- Version stamp in About / footer from `pyproject.toml`.

### Phase 3 — Later

- macOS `.app` (separate build machine; no Amazon fetcher).
- Linux AppImage (optional).
- Tauri shell (only if we want native window chrome — not required for beta).

---

## Files to change (Phase 1 checklist)

| File | Change |
|------|--------|
| `shared/install_paths.py` | **New** — frozen/data/bundle roots |
| `shared/profile_paths.py` | `ROOT` → `data_root()` |
| `server.py` | `--run-fetcher` early exit; `_argv` / `_python_executable`; `static_root` for handler |
| `baklog_fetcher_dispatch.py` | **New** — manifest key → `main()` |
| `auth/manager.py`, `auth/secrets.py`, `auth/bundle.py` | Use `data_root()` / `bundle_root()` |
| `fetchers/registry.py` | `MANIFEST_PATH` from `bundle_root()` |
| `shared/safe_write.py` | Align ROOT |
| `packaging/baklog.spec` | **New** |
| `packaging/build_windows.ps1` | **New** |
| `docs/BETA_SETUP.md` | **New** — tester instructions |
| `tracker.html` Beta tab | Replace `[setup link]` with release URL when live |
| `.github/workflows/release.yml` | **New** (Phase 2) — optional CI build |

---

## Test matrix (before sending invites)

Manual on a **clean Windows VM** (no Python, no repo clone):

- [ ] Double-click `BAKLOG.exe` → server listens on 8765
- [ ] Dashboard loads (CSS/JS, no 404s)
- [ ] Connections → Steam Connect → Chrome opens, credentials saved under `data_root()/profiles/...`
- [ ] Refresh Steam → fetch completes, `games_steam.json` written beside exe
- [ ] Library tab shows games
- [ ] Second launch: data persists (profiles, JSON)
- [ ] Wishlist + ITAD fetch (one each) smoke test
- [ ] Copy bug bundle works
- [ ] Quit and restart: no port-in-use zombie

---

## Distribution & invite email link

| Phase | `[setup link]` value |
|-------|----------------------|
| 0 | `https://github.com/Ogrods/BAKLOG/releases/tag/v0.6.0-beta.1` |
| 1 | Same pattern, asset `BAKLOG-win64.zip` |
| Later | `https://baklog.app/download` redirect to latest release |

Release notes template: Chrome/Edge required, Windows 10/11, free forever to import library, invite-only Supabase login if enabled.

---

## Risks & mitigations

| Risk | Mitigation |
|------|------------|
| SmartScreen blocks unsigned exe | Phase 0 zip for friends; sign in Phase 2; README says "More info → Run anyway" |
| PyInstaller misses hidden import | Iterative build + import smoke test script |
| Large download (~80–150 MB) | onedir zip; document size in BETA_SETUP |
| Fetcher subprocess regressions | `--run-fetcher` integration test in CI (Windows job) |
| Chrome not installed | Clear error in Connections + BETA_SETUP prerequisite |

---

## Out of scope for v1 frozen build

- Bundling Chromium (too large; use system Chrome/Edge).
- Auto-update channel (manual re-download for beta waves).
- macOS/Linux frozen binaries.
- Removing Python from **dev** workflow (unchanged).

---

## Next action

Start **Phase 1** implementation: `shared/install_paths.py` + `--run-fetcher` dispatch. That unblocks the first real `BAKLOG.exe` smoke test on this machine.
