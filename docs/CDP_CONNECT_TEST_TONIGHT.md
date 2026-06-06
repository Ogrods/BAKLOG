# CDP Connect test — tonight (conn-test profile)

**Server:** `BAKLOG_AUTH_DISABLED=1` + `python server.py` (running on http://127.0.0.1:8765)  
**Profile:** `conn-test` (throwaway — does not touch your main library)  
**Harness:** `scripts/test_cdp_connect_flows.py`  
**Results file:** `docs/cdp-connect-test-results.json` (updated after each command)

## Quick status (automated preflight — 2026-06-06)

| Step | Result |
|------|--------|
| Server up | yes (`authRequired: false` for this session) |
| Chrome/Edge | found |
| Profile `conn-test` | created and active |
| All 5 providers | **disconnected** (expected — sign-in is manual) |
| GOG connect trial | browser launched; **120s wait timed out** (no sign-in completed) |

## Per-provider loop

For each provider below, run **one command** in PowerShell from the repo root. Complete sign-in in the headed browser window. The script waits up to 5 minutes, then runs fetchers and writes row counts.

### 1. GOG (web)

```powershell
.\.venv\Scripts\python.exe scripts\test_cdp_connect_flows.py fetch --provider gog --launch-connect --wait-connect 300
```

- Land on **gog.com library/account** before the window closes.
- Expect: `gog` + `wishlistGog` fetchers exit 0; `games_gog.json` populated under `profiles/conn-test/`.

### 2. Battle.net (+ reconnect chip check)

```powershell
.\.venv\Scripts\python.exe scripts\test_cdp_connect_flows.py fetch --provider battlenet --launch-connect --wait-connect 300
```

- Open **account.battle.net/games** so the session is active.
- Script auto-tests **Disconnect → reconnect start** after a successful fetch.

### 3. Nintendo

```powershell
.\.venv\Scripts\python.exe scripts\test_cdp_connect_flows.py fetch --provider nintendo --launch-connect --wait-connect 300
```

- Let **ec.nintendo.com/my/transactions/** finish loading.

### 4. Humble Bundle

```powershell
.\.venv\Scripts\python.exe scripts\test_cdp_connect_flows.py fetch --provider humble --launch-connect --wait-connect 300
```

- Clear any **CAPTCHA**; library page opens after sign-in.
- Expect: `humble` + `wishlistHumble` fetchers.

### 5. EA App

```powershell
.\.venv\Scripts\python.exe scripts\test_cdp_connect_flows.py fetch --provider ea --launch-connect --wait-connect 300
```

- After sign-in, **EA deals page** confirms the session.

## Manual UI path (alternative)

1. Open http://127.0.0.1:8765/#connections  
2. Confirm header profile is **conn-test**.  
3. Click **Connect** per provider; complete sign-in.  
4. Dashboard → **Fetcher health** → click the store chip (Shift+click for refresh).  
5. Check `profiles/conn-test/games_<store>.json` for row counts.

## Check auth without fetch

```powershell
.\.venv\Scripts\python.exe scripts\test_cdp_connect_flows.py status
```

## Record results

After each provider, inspect `docs/cdp-connect-test-results.json` or fill in:

| Provider | Connect | Auth status | Fetch exit | games_*.json rows | Notes |
|----------|---------|-------------|------------|-------------------|-------|
| GOG | | | | | |
| Battle.net | | | | | reconnect chip? |
| Nintendo | | | | | |
| Humble | | | | | |
| EA | | | | | |

## Restart server (if needed)

```powershell
# From repo root — use venv, disable Supabase gate for profile testing
$env:BAKLOG_AUTH_DISABLED = "1"
Remove-Item Env:\BAKLOG_PROFILE -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe server.py
```

## Automated regression (no live sign-in)

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_cdp_browser.py tests/test_auth_status_platform.py tests/test_profile_credentials_thread.py -q
```
