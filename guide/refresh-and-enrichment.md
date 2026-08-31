# Refresh and enrichment

Keep library data current and backfill metadata after fetchers run.

## While the app is open

**Auto-refresh stale stores** (default on, Connections tab): quietly refreshes one store older than 24h every ~30 min while the dashboard tab is open. Toggle off on Connections if you prefer manual control.

**ITAD auto-refresh** (default on): deal prices refresh on a 15-60 min schedule from the Fetcher health panel.

**Auto-enrich** (default off): after a library fetch adds games, optionally queues HLTB, reviews, covers, and co-op tags. Turn it on from the Fetcher health panel if you want that.

On the free tier, store refresh is one store at a time, on demand (click a fetcher chip). Pro adds scheduled refresh while the app is closed - see [FAQ](faq.md).

## Fetcher health row

Click any chip in **Fetcher health** to enqueue that fetcher. Output streams live into a log panel and the chip refreshes when the run finishes.

- Shift+click on supported library/wishlist chips adds `--refresh`
- Shift+click on HLTB, Reviews, Covers enrichers adds `--retry-misses`

**HLTB backlog:** if many titles still need hours (or you Shift+click to retry cached misses), BAKLOG shows a confirm dialog with a rough ETA before starting. Matched hours are saved as the run progresses. If HowLongToBeat's search API is down, the enricher stops after a streak of empty results so it does not mark your whole library as "no match" - bump `howlongtobeatpy` if needed, then Shift+click HLTB to retry.

**Stall watchdog:** when a fetcher runs via `server.py`, if stdout is silent for about 60s the server injects `[server] no output for Ns - still running (PID …)` into the log panel (repeats). If silence continues for 180s with no heartbeat, the process is force-killed. HLTB prints heartbeats during slow lookups so healthy runs stay alive.

Run logs also land in `profiles/<id>/cache/runs/*.jsonl`.

## Scheduled refresh (app closed)

For refreshes while BAKLOG is closed, use the helper script for your OS or rely on Pro scheduled refresh (tray or OS scheduler).

Scripts and UI runs use the same fetch sequence and log to `refresh.log`.

**Windows** (`refresh.ps1`):

```powershell
Set-Location "C:\path\to\steam-backlog"
.\refresh.ps1
```

Weekly scheduled task example (Sundays at 9:00):

```powershell
schtasks /create /SC WEEKLY /D SUN /TN "BAKLOG Refresh" /TR "powershell -ExecutionPolicy Bypass -File \"C:\path\to\steam-backlog\refresh.ps1\"" /ST 09:00
```

**macOS / Linux** (`refresh.sh`):

```bash
chmod +x refresh.sh   # first time only
./refresh.sh
```

Weekly cron example (Sundays at 9:00):

```bash
crontab -e
# add:
0 9 * * 0 cd /path/to/steam-backlog && ./refresh.sh
```

`refresh.sh` skips `fetch_amazon.py` on non-Windows hosts (launcher DB is Windows-only). Use the Prime Gaming web Connections card + `fetch_amazon.py --source web` on macOS/Linux.

## Enrichment scripts

| Script | Purpose |
|--------|---------|
| `enrich_steam_reviews.py` | Backfill Steam review % on non-Steam rows via Steam store search |
| `enrich_cross_store_images.py` | Backfill `header_image` / `library_image` from the Steam CDN for non-Steam rows |
| `enrich_hltb.py` | Backfill HLTB hours on any `games_*.json` row missing them |
| `enrich_protondb.py` | Backfill ProtonDB Linux / Steam Deck compatibility tiers on Steam-matched rows; no API key |
| `fetch_itad.py` | Cross-store deal prices → `itad_prices.json`; refreshes FX rates |
| `fetch_fx.py` | Refresh FX rates only (`cache/fx_rates.json`, Frankfurter; 24h cache) |

Wrapper: `python -m enrichers <cmd>` for `hltb`, `steam-reviews`, `cross-store-images`.

**Data attribution:** BAKLOG surfaces third-party data from [ProtonDB](https://www.protondb.com) (Steam Deck / Linux tiers, ODbL), [IsThereAnyDeal](https://isthereanydeal.com/) (deal prices), [GamerPower](https://www.gamerpower.com/) (giveaway feed), and [HowLongToBeat](https://howlongtobeat.com/) (completion hours). Store logos and trademarks belong to their respective owners.

## Exit codes

Every fetcher script prints `=== name started at … ===` and a footer summary with elapsed time.

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | Runtime or config error |
| `2` | Suspicious empty result (or ITAD resolved zero titles) - stale data preserved by default |
| `3` | Drift guard refused write |
| `4` | Auth failure (expired or invalid credential) |

Fetcher failures show in the Fetcher health panel and run logs - they are not auto-sent to the bug-report endpoint. See [Getting help](getting-help.md).

## Fetcher flags reference

| Flag | Effect |
|------|--------|
| `--refresh` | Ignore cache, refetch everything |
| `--retry-misses` | Re-attempt enricher rows cached as no match |
| `--only-new` | Only fetch games not already in the store JSON file |
| `--skip-hltb` | Skip HowLongToBeat lookups (faster) |
| `--allow-empty` | Allow writing a zero-item result |

Per-store Connect steps: [Connecting stores](connecting-stores.md).
