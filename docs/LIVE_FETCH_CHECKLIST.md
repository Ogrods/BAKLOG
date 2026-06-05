# Pre-go-live live fetch checklist

Use this before shipping when fixture tests pass but store APIs may have drifted. See [AUDIT_FINDINGS.md](AUDIT_FINDINGS.md) Section 6 for known-broken context.

## Prerequisites

1. Start the app: `python server.py` (listens on `127.0.0.1:8765`).
2. Connect each store you care about on **Connections**.
3. Optional queue/orchestration smoke: `python scripts/live_test_fetcher.py` (Windows; exercises run manager, not per-store APIs).

## Per-store manual pass

Run **one library fetch** per connected store from Connections or the fetcher log. Record result in the table below.

| Store key | Connected? | Fetch exit 0? | Games > 0? | Notes |
|-----------|------------|---------------|------------|-------|
| steam | | | | |
| gog | | | | |
| psn | | | | |
| epic | | | | |
| amazon | | | | |
| xbox | | | | |
| battlenet | | | | |
| ubisoft | | | | |
| nintendo | | | | |
| itch | | | | |
| humble | | | | |
| ea | | | | |
| epic_wishlist | | | | |
| itad | | | | enricher, not library |

**Pass criteria:** exit code 0 and non-empty `games_<store>.json` (or documented empty library). Transient errors → retry once; auth errors → reconnect; API shape changes → file under `audit-fetchers-repair` in AUDIT_FINDINGS.

## Quick manifest listing

```bash
python scripts/store_fetch_checklist.py
```

With server up, add `--ping` to verify `/api/runs` responds.

## Debug raw dumps (optional)

Do **not** leave `*_raw.json` on disk in normal use. Enable only while debugging:

```bash
set BAKLOG_RAW_DUMPS=1
```

Then re-run the failing fetcher with its `--dump-raw` flag where supported.
