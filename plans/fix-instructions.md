# Fix Instructions — 3 Remaining Items

## 1. `fetch_humble_wishlist.py` — multi-line `with` → `try/finally`

**File:** `fetchers/fetch_humble_wishlist.py`

**Problem:** Lines 203-208 use a multi-line `with` block:

```python
    with launch_persistent_profile(
        str(profile),
        headless=False,
        window_position=_WL_WINDOW_POS,
        window_size=_WL_WINDOW_SIZE,
    ) as ctx:
```

When `function returns` at line 250 inside this `with` block, `ctx.close()` blocks for up to 26s killing headless Chrome.

**Fix** — Change three things:

**a) Add `import threading` (line 19):**

```python
import sys
import threading
import time
```

**b) Replace the `with` block opening (lines 203-208):**

```python
    ctx = launch_persistent_profile(
        str(profile),
        headless=False,
        window_position=_WL_WINDOW_POS,
        window_size=_WL_WINDOW_SIZE,
    )
    try:
```

**c) Add `finally` before `def _build_row` (after line 250):**

```python
        return items, False
    finally:
        threading.Thread(target=ctx.close, daemon=True).start()


def _build_row(item: WishlistItem, hltb: dict | None) -> dict:
```

---

## 2. `build_free_claims.py` — Steam User-Agent

**File:** `fetchers/build_free_claims.py`, line 40

**Problem:** The Steam storesearch uses a generic User-Agent that Steam may reject with 401:

```python
STEAM_HEADERS = {"User-Agent": "Mozilla/5.0 backlog/1.0"}
```

**Fix** — Change to the same real Chrome UA used in the proxy:

```python
_STEAM_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
```

Then find where `STEAM_HEADERS` is used in the file and replace the UA reference. For example, if it's used like:

```python
resp = requests.get(STEAM_STORESEARCH_URL, headers=STEAM_HEADERS, ...)
```

Change to:

```python
resp = requests.get(STEAM_STORESEARCH_URL, headers={"User-Agent": _STEAM_UA}, ...)
```

---

## 3. `/api/proxy/` auth exemption — documentation

**File:** `server.py`, line 981

**Problem:** The `/api/proxy/steam-search` and `/api/proxy/steam-reviews` endpoints are exempt from Supabase JWT auth, allowing unauthenticated proxy requests to Steam. This is necessary because the add-game modal uses bare `fetch()` (no Bearer token) for Steam search.

**Current code** (already correct, just needs documenting):

```python
if path.startswith("/api/proxy/"):
    return True
```

**Documentation** — Add a comment explaining the boundary:

```python
# /api/proxy/* endpoints proxy public third-party APIs (Steam storesearch,
# appreviews). They accept any search term but only proxy to Steam's
# read-only endpoints — no credentials forwarded, no write access.
# These must remain unauthenticated because the add-game modal calls them
# via bare fetch() (no Bearer token).
if path.startswith("/api/proxy/"):
    return True
```
