# Fetcher audit findings (static code + UI)

Audit date: 2026-06-05. Method: static review of Python fetch scripts and the dashboard fetcher-health UI (`js/fetcher-health.js`, `app.css`, `index.html`). No live store connections were exercised.

Cross-links: [AUDIT_FINDINGS.md §6](AUDIT_FINDINGS.md#section-6--store-integrations-known-broken-context), [FETCHER_CONNECTIONS.md](FETCHER_CONNECTIONS.md), [LIVE_FETCH_CHECKLIST.md](LIVE_FETCH_CHECKLIST.md).

## Summary

| Priority | Python | UI | Status this pass |
|----------|--------|-----|------------------|
| P0 | 2 | 1 | Fixed |
| P1 | 4 | 3 | Fixed |
| P2 | 2 | 1 | Fixed |

## Python fetchers

### P0 — fixed

| Finding | Location | Fix |
|---------|----------|-----|
| Xbox wishlist wrote `wishlist_state.json` on every empty wishlist | `fetch_xbox_wishlist.py` ~463–484 | Dump only with `--dump-state` or `BAKLOG_RAW_DUMPS=1` |
| `--allow-empty` ignored on manual exit-2 empty-library paths | `fetch_ubisoft.py` 334–339, `fetch_nintendo.py` 260–265, `fetch_battlenet.py` 278–283, `fetch_ea.py` 341–345 | Route through `refuse_empty_result()` |

### P1 — fixed

| Finding | Location | Fix |
|---------|----------|-----|
| Steam auth failures exited 1 without `mark_invalid` | `fetch_games.py`, `fetch_wishlist.py` | Catch HTTP 401/403 → `mark_invalid("steam")` + exit 4 |
| Empty Steam library raised before `refuse_empty_result` | `steam_client.py` 96–100 | Return `[]` instead of raising |
| GOG non-auth `HTTPError` re-raised as traceback | `fetch_gog.py` 596–602 | Structured exit 1 + message |
| Duplicated `raw_dump_json()` helpers; dumps not gated | `fetch_ubisoft.py`, `fetch_battlenet.py`, `fetch_nintendo.py`, `fetch_ea.py`, `fetch_amazon.py` | `shared/raw_dumps.profile_raw_dump_path()` |

### P2 — fixed

| Finding | Location | Fix |
|---------|----------|-----|
| Stale user-facing cache paths | `fetch_epic.py` 269, `fetch_nintendo.py` 262, `fetch_amazon.py` 392 | Profile-scoped paths in help/errors |
| `AUTH_EXIT_SCRIPTS` contract incomplete | `tests/test_fetcher_auth_exit.py` | Extended list + generic exit-4 test |

### Dimensions reviewed (pass / note)

| Dimension | Verdict | Notes |
|-----------|---------|-------|
| Auth exit contract (exit 4 + `mark_invalid`) | improved | Steam + existing CDP/session fetchers aligned |
| Empty-result guard (`refuse_empty_result`) | improved | Ubisoft/Nintendo/Battle.net/EA honor `--allow-empty` |
| Drift guard (`refuse_drift_result`) | pass | Present on major library fetchers |
| Debug raw dumps | improved | Gated via `BAKLOG_RAW_DUMPS` / `--dump-raw` |
| Heartbeat / stall-kill (180s) | gap | Long HLTB/detail loops still lack `run_with_heartbeat` on some fetchers |
| Manifest ↔ script parity | pass | `test_fetcher_manifest_audit.py` |
| `_configure_stdout()` duplication | nice-to-have | Copy-pasted per script; candidate for `fetchers._base.configure_stdout` |
| Per-store unit tests | partial | PSN/Xbox/Ubisoft main scripts lack dedicated `test_fetch_*` modules |

## Fetcher front-end UI

### P0 — fixed

| Finding | Location | Fix |
|---------|----------|-----|
| Mobile global status pill is icon-only (text clipped) | `js/fetcher-health.js` `updateGlobalFetcherIndicator`, `app.css` ~4943 | `aria-label` synced with status text |

### P1 — fixed

| Finding | Location | Fix |
|---------|----------|-----|
| Chips rely on `title` only | `chipHtml` ~3010 | `aria-label` on chip buttons |
| Layout toggle missing pressed state | `index.html` 127, `cycleStatLayout` | `aria-pressed` + mode label |
| Run log status not exposed to AT | `.fh-log-status` ~2082 | `aria-live="polite"` |

### P2 — fixed

| Finding | Location | Fix |
|---------|----------|-----|
| Dead reconnect-chip UI CSS + handlers | `app.css` 1843–1867, 2064–2118, 5562–5576; `js/bind-events.js` 135–147 | Removed; chips use `data-fetcher-connect` |

### Dimensions reviewed

| Dimension | Verdict | Notes |
|-----------|---------|-------|
| Chip → run / Shift+refresh wiring | pass | `bind-events.js` + `fetcherRunner` |
| Reconnect UX (exit 4 → chip state) | pass | `isFetcherReconnectRequired`, auth cooldown |
| Popover scroll / nested scroll owners | gap | `.fetcher-popover-scroll` + `.fh-log-body` still nested |
| Full `innerHTML` rebuild on render | gap | Open `<details>`, focus, checkbox state reset |
| Module size (~3.1k lines) | gap | `fetcher-health.js` monolith |

## Recommended (not done this pass)

1. **Split `js/fetcher-health.js`** into `js/fetcher/` modules (`auth-cooldown`, `freshness`, `sources`, `global-status`, `auto-run`, `runner/`, `ui/`) with a re-export barrel.
2. **Diff/patch render** in `renderDashboardFetcherHealth` so open details, checkboxes, and focus survive re-render.
3. **Single-scroll-owner** redesign for the fetcher popover.
4. **`HeartbeatTimer` / `run_with_heartbeat`** on long Steam/PSN/GOG/Amazon/itch enrichment loops to avoid 180s stall-kill.
5. **Fetcher-main tests** for PSN, Xbox library, Ubisoft library scripts.
6. **Consolidate `_configure_stdout()`** into `fetchers._base.configure_stdout`.

## Verification

```bash
python -m ruff check .
python -m pytest -q tests/test_fetcher_auth_exit.py tests/test_fetcher_manifest_audit.py tests/test_fetch_* tests/test_raw_dumps.py
npm test -- tests/fetcher-health.test.js tests/a11y/index-axe.test.js
```
