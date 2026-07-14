# Battle.net Connect Window Closes Immediately

## Symptom

When clicking "Connect" on the Connections page for Battle.net, a headed Chrome/Edge
browser window appears briefly and closes before the user can sign in. The window
vanishes in under 1-2 seconds.

## Root Cause

An **unhandled exception** in [`auth/connect_extractors.py:198-207`](auth/connect_extractors.py:198)
causes the entire headed-browser session to terminate when the persistent profile
contains stale/expired cookies.

### Exception Propagation Chain

```
extract_battlenet_session(context)
  ├─ _battlenet_has_session(context)        # finds ANY battle.net cookie → True
  ├─ _cookie_header(context.cookies(), ...)  # builds cookie string
  ├─ probe_session(header)                   # makes HTTP GET to games-and-subs API
  │   └─ BattleNetClient.get_raw_account()
  │       └─ 401/403 → raises BattleNetAuthError   ← UNCAUGHT!
  ├─ ❗ exception propagates through run_connect_poll (connect_loop.py:37)
  ├─ ❗ through _extract_battlenet_inline (runner.py:164)
  ├─ ❗ through run_browser_auth (runner.py:1742)
  └─ ❗ exits `with launch_persistent_profile(...)` → context.close() → KILLS BROWSER
```

### Why `_battlenet_has_session` Returns True

The function at [`auth/connect_extractors.py:61-66`](auth/connect_extractors.py:61) checks
for **any cookie** whose domain ends with `battle.net`:

```python
def _battlenet_has_session(context: Any) -> bool:
    for c in context.cookies():
        domain = (c.get("domain") or "").lstrip(".")
        if domain.endswith("battle.net") and c.get("name") and c.get("value"):
            return True
    return False
```

After a prior successful Connect, the persistent profile at
`profiles/<id>/cache/auth/battlenet/` contains various cookies for `battle.net`
domains (session cookies, tracking cookies, region preferences). When these
cookies expire (Battle.net sessions last ~7 days per the registry), any
subsequent "Connect" attempt:

1. Detects the stale cookies → `_battlenet_has_session` returns `True`
2. Builds a cookie header from them
3. Probes the API → gets 401/403 → raises `BattleNetAuthError`
4. **Browser window closes before the user even sees a login page**

### Why This Is a Regression

The [`_battlenet_has_session` in `auth/runner.py` lines 134-147](auth/runner.py:134) has a
**different implementation** that properly handles 401/403 by returning `False`
(using an actual HTTP request):

```python
def _battlenet_has_session(context) -> bool:
    """True when the Playwright context can read the games-and-subs API."""
    try:
        resp = context.request.get(ACCOUNT_URL, timeout=30_000)
        if resp.status == 200: ...
        if resp.status in (401, 403): return False
    except Exception: pass
    return False
```

This function is **dead code** — it's defined in `runner.py` but never called during
the connect flow. The connect flow imports `extract_battlenet_session` from
`connect_extractors.py`, which uses the weaker cookie-only check and then calls
`probe_session` without catching exceptions.

### Comparison With Other Providers

| Provider             | Extraction Function                                             | Handles Stale Cookies?                                                |
| -------------------- | --------------------------------------------------------------- | --------------------------------------------------------------------- |
| GOG                  | [`extract_gog_session`](auth/connect_extractors.py:161)         | ✅ Just reads cookie, returns it — no API probe                       |
| Humble               | [`extract_humble_session`](auth/connect_extractors.py:178)      | ✅ Returns None if orders API fails (caught in `_humble_has_session`) |
| Battle.net           | [`extract_battlenet_session`](auth/connect_extractors.py:198)   | ❌ `probe_session` raises on 401/403 — unhandled                      |
| Battle.net (fetcher) | [`fetch_battlenet.py:226-255`](fetchers/fetch_battlenet.py:226) | ✅ Proper try/except with fallback to browser jar                     |

### When Does This Happen?

- The user has **previously connected** Battle.net (so the persistent profile exists)
- The cookies have **expired** (after ~7 days)
- The user clicks **"Connect"** (not "Reconnect" — "Reconnect" calls
  [`clear_browser_session`](auth/manager.py:623) which wipes the profile)

## Fix Plan

### 1. Catch `BattleNetAuthError` in `extract_battlenet_session`

In [`auth/connect_extractors.py:198-207`](auth/connect_extractors.py:198), wrap the
`probe_session(header)` call in a try/except that catches `BattleNetAuthError`
and returns `None`:

```python
def extract_battlenet_session(context: Any) -> dict[str, str] | None:
    from clients.battlenet_client import BattleNetAuthError, probe_session

    if not _battlenet_has_session(context):
        return None
    header = _cookie_header(context.cookies(), (".battle.net", "battle.net"))
    if not header:
        return None
    try:
        probe_session(header)
    except BattleNetAuthError:
        return None
    return {"BATTLENET_COOKIE": header}
```

This is the minimal fix. When `probe_session` fails, the poll loop will keep
running, the browser stays open, and the user can sign in normally. After they
sign in, fresh cookies will be set, the next poll cycle will detect them, and
the probe will succeed.

### 2. (Optional but recommended) Remove dead `_battlenet_has_session` from runner.py

The unused function at [`auth/runner.py:134-147`](auth/runner.py:134) should be
removed to avoid confusion. It was a leftover from the Playwright-era
implementation.

### 3. Verify the fix

1. Start the dev server with `BAKLOG_ADMIN=1`
2. If a Battle.net profile dir already exists at
   `profiles/<current>/cache/auth/battlenet/`, the stale cookies should trigger
   the bug path. After the fix, the window should stay open and show the login page.
3. If no profile dir exists (clean state), do a full Connect cycle to verify it
   still works.
