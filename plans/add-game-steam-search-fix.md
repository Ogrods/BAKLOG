# Add-Game Steam Search Fix Plan

## Symptom

When using "+ Add game" modal and clicking "Search Steam", the browser console shows a CORS error and the search fails. Steam's `store.steampowered.com` API doesn't send `Access-Control-Allow-Origin` headers, so browser `fetch()` calls from `localhost:8765` are blocked.

## Root Cause

[`steamSearch()`](js/add-game-modal.js:119) and [`steamAppReviews()`](js/add-game-modal.js:127) use bare `fetch()` to call `store.steampowered.com` directly. The browser blocks these cross-origin requests because Steam's response lacks CORS headers.

## Fix Plan

### 1. Add server-side proxy handlers in [`server.py`](server.py)

Add two GET routes and handlers:

**Route:** `GET /api/proxy/steam-search?term=<term>`
**Handler:** `_handle_proxy_steam_search()` — proxies to `https://store.steampowered.com/api/storesearch/`
**Returns:** Same JSON as Steam API (passthrough)

**Route:** `GET /api/proxy/steam-reviews?appid=<id>`
**Handler:** `_handle_proxy_steam_reviews()` — proxies to `https://store.steampowered.com/appreviews/<id>`
**Returns:** Same JSON as Steam API (passthrough)

Both handlers:

- Accept `term` or `appid` query params
- Make HTTP GET via `urllib.request` (stdlib, no extra deps)
- Forward JSON response back to client
- Return `502 Bad Gateway` on upstream failure

### 2. Update JS in [`add-game-modal.js`](js/add-game-modal.js)

Change `steamSearch()` to call `/api/proxy/steam-search?term=...` instead of direct Steam URL.

Change `steamAppReviews()` to call `/api/proxy/steam-reviews?appid=...` instead of direct Steam URL.

**Do NOT reformat the file.** Only change the URL and error handling in these two functions.

### 3. End-to-end audit of add-game pipeline

| Step                           | File                    | What happens                         | Status |
| ------------------------------ | ----------------------- | ------------------------------------ | ------ |
| 1. User types title            | `add-game-modal.js`     | `titleEl.value` captured             | ✅     |
| 2. User clicks Search Steam    | `add-game-modal.js:283` | `runSearch()` called                 | ✅     |
| 3. API call (CORS issue)       | `add-game-modal.js:119` | `fetch()` to Steam blocked **← FIX** | ❌     |
| 4. Response parsed             | `add-game-modal.js:123` | `res.json()` → `data.items`          | ✅     |
| 5. Results rendered            | `add-game-modal.js:295` | Buttons with `data-appid`            | ✅     |
| 6. User clicks match           | `add-game-modal.js:312` | Click handler fires                  | ✅     |
| 7. Refetch + find match        | `add-game-modal.js:316` | `steamSearch()` called again → CORS  | ❌     |
| 8. `importSteamMatch`          | `add-game-modal.js:179` | Builds game object                   | ✅     |
| 9. Fetch reviews (CORS)        | `add-game-modal.js:183` | `steamAppReviews()` → CORS           | ❌     |
| 10. `runWithDuplicateCheck`    | `add-game-modal.js:220` | Checks `game-duplicate.js`           | ✅     |
| 11. `addManualGame`            | `personal-storage.js`   | Saves to personal data               | ✅     |
| 12. Server PUT /api/personal   | `server.py:1802`        | Persists the doc                     | ✅     |
| 13. `refreshAfterManualChange` | `library-load.js`       | Reloads library view                 | ✅     |

All steps work except 3, 7, 9 — all three are CORS issues with direct `fetch()` to Steam.

### 4. Verify after fix

1. Restart dev server
2. Open dashboard, click + Add game
3. Type a game title, click Search Steam
4. Verify results display
5. Click a result to import
6. Verify game appears in library
