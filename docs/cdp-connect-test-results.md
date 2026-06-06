# CDP connect test results — 2026-06-06

**Environment:** Windows, `BAKLOG_AUTH_DISABLED=1`, profile `conn-test`  
**Server:** http://127.0.0.1:8765  
**Automated pytest:** 38 passed, 1 skipped (`test_cdp_browser`, `test_auth_status_platform`, `test_profile_credentials_thread`)

## Summary

| Provider | Connect | Auth status | Fetch | games JSON rows | Notes |
|----------|---------|-------------|-------|-----------------|-------|
| GOG (web) | browser opened | disconnected | not run | — | 120s sign-in wait timed out |
| Battle.net | browser opened | disconnected | not run | — | 15s wait timed out |
| Nintendo | browser opened | disconnected | not run | — | 15s wait timed out |
| Humble | browser opened | **connected** | humble exit **4**, wishlistHumble exit **2** | 0 / missing | Connect succeeded; fetchers failed (re-run after full library load) |
| EA App | browser opened | disconnected | not run | — | 15s wait timed out |

## Tonight — finish manual sign-in

Use [CDP_CONNECT_TEST_TONIGHT.md](CDP_CONNECT_TEST_TONIGHT.md). Per provider:

```powershell
.\.venv\Scripts\python.exe scripts\test_cdp_connect_flows.py fetch --provider <gog|battlenet|nintendo|humble|ea> --launch-connect --wait-connect 300
```

## Humble follow-up

Humble shows **connected** on `conn-test` but fetchers exited non-zero. Likely causes:
- Empty library on throwaway profile (no purchases)
- Browser profile not fully synced to fetch script path
- Re-run: `fetch --provider humble` after confirming library page loads in Connections

Check server log / fetcher panel for auth or parse errors.

## Harness commands

```powershell
.\.venv\Scripts\python.exe scripts\test_cdp_connect_flows.py preflight
.\.venv\Scripts\python.exe scripts\test_cdp_connect_flows.py status
.\.venv\Scripts\python.exe scripts\test_cdp_connect_flows.py fetch --provider gog --launch-connect --wait-connect 300
```

Machine-readable log: [cdp-connect-test-results.json](cdp-connect-test-results.json)
