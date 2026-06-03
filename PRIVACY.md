# Privacy

BAKLOG is a **local-only** desktop tool. It does not have a server, account
system, telemetry, or analytics. The "server" referenced in the README is a
`http://127.0.0.1` Python process that exists only to serve files to your own
browser tab. Nothing leaves your machine except direct calls you make to the
storefronts and enrichment services listed below.

Last updated: 2026-06-02.

## TL;DR

- Everything is stored locally on your computer.
- BAKLOG talks to each storefront on your behalf using the credentials you
  provide. Each storefront sees its own normal API/scrape traffic from you.
- We have no servers, so we cannot collect data even if we wanted to. The
  authors never receive your library, wishlist, notes, or credentials.
- Backups of your personal data and fetched libraries are written locally and
  not transmitted anywhere.

## Acting on your behalf, with your own data

BAKLOG is not a scraping service and does not crawl storefronts on its own. It
is a local automation tool that does, on your machine, what you could do by
hand in your own logged-in browser:

- **You** sign in to each store, with **your** account, in a browser window on
  **your** computer.
- BAKLOG then reads back **only your own account's** library/wishlist —
  the same data those pages already show you when you're logged in.
- Each request goes **directly from your machine to the store**, authenticated
  as you, from your own IP. There is no shared server, no pooled credentials,
  and no central copy of anyone's catalog.

In other words, the only data BAKLOG ever touches is your own, and the only
party acting is you — BAKLOG is just the automation. For the per-store access
method (official API key, official OAuth, or replaying your own web session)
and the terms-of-service caveats, see
[SECURITY.md → How BAKLOG reaches each store](SECURITY.md#how-baklog-reaches-each-store).

## What is stored, where, and why

### Credentials
| What | Where | Why |
|------|-------|-----|
| OAuth refresh tokens (Epic, Battle.net, Nintendo) | `cache/<store>/session.json` and/or the OS keychain via Python `keyring` | Re-auth without re-prompting |
| Session cookies (GOG, PSN NPSSO, Xbox, Ubisoft, itch, Epic storefront) | `.env` and/or `cache/auth/profiles/<store>/` (Chrome/Edge user-data from CDP sign-in) | Same as above |
| API keys (Steam Web API, OpenXBL, ITAD, HowLongToBeat) | `.env` | Required by those APIs |
| Encrypted secret bundle | DPAPI-protected blob (Windows) or the `cryptography` AES-GCM keyring fallback | Encrypted-at-rest variant used by the Connections page |

Credentials are never written to fetched `games_*.json` files, never logged in
plain text to stdout, and never sent to the project authors.

### Library + wishlist data
- `games_*.json` — one file per store, holds library/wishlist titles, your
  playtime/last-played as the store reports it, store cover art URLs, genre
  tags, and any enrichment data (Steam reviews, HowLongToBeat hours, ITAD
  prices). Owned by the corresponding `fetch_*.py`.
- `itad_prices.json` — current best-anywhere prices and historical-low flags
  fetched from IsThereAnyDeal.
- `data/games_backups/<stem>/` — last 10 successful writes of each
  `games_*.json` so a bad fetcher run can't wipe your data. Local only.

### Your personal annotations
- `data/personal.json` — your status (backlog / next / playing / etc.), notes,
  priority, HLTB hour overrides, and the `hidden` flag (Hidden games panel).
  Keyed by `store:id`.
- `data/personal_backups/personal-<timestamp>.json` — server-side rotated
  backups (the local `http://127.0.0.1` server writes one on every PUT). Local
  only.
- `manualGames` localStorage key + the `manual[]` array in `personal.json` —
  custom games you added via the Add game modal.

### Browser-side data
- `localStorage` mirrors the same `personal.json` shape plus UI preferences
  (sort order, picks tab, picks collapsed, etc.). Nothing in `localStorage`
  leaves the browser tab.
- `localStorage.baklog-error-log` — rolling 200-entry capture of uncaught
  errors and unhandled promise rejections from this browser tab. Survives
  reloads so a "Copy bug bundle" click can include history across sessions.
  Never sent anywhere. See **Error logs and bug reporting** below.

### Error logs and bug reporting
When an uncaught error or unhandled promise rejection fires, BAKLOG:

1. Captures it (message, stack, source/line, timestamp) into
   `window.__baklogErrors` for this tab.
2. Mirrors it into the `baklog-error-log` localStorage ring (last 200
   entries, oldest evicted).
3. Surfaces a sticky red toast in the top-right corner with **Copy bug
   bundle / Errors only / Details / Dismiss** buttons.

**"Copy bug bundle"** places a sanitized JSON payload on your clipboard. The
bundle is a whitelist — only these fields are included:

| Field | Why |
|-------|-----|
| `app_version` | from the `<meta name="baklog-version">` tag |
| `generated_at` | ISO timestamp of the click |
| `ua` | `navigator.userAgent`, truncated to 256 chars |
| `runtime.view` | current view name (e.g. `library`) |
| `runtime.data_version` | internal `_dataVersion` counter |
| `runtime.active_filter_count` | how many filters are applied |
| `runtime.table_fingerprint` | opaque hash-shaped string used for cache invalidation |
| `runtime.last_render_ms` | most recent `renderTable()` duration |
| `runtime.dash_stats` | dashboard render counters (full/replay/skipped) |
| `errors.session[]` | uncaught errors captured in the current tab |
| `errors.persisted[]` | rolling history from `baklog-error-log` |

The bundle deliberately **does not** include `state.personal` (your notes,
statuses, priorities), `manualGames`, library/wishlist JSON, credentials,
`.env` contents, cookies, or any path that contains your home directory.
Browser stack traces reference the served URL (e.g.
`http://localhost:8765/js/foo.js:123:45`), not your filesystem path.

Once on your clipboard, the bundle is JSON you can paste anywhere — a
GitHub issue, an email, a paste buffer for inspection. What happens after
the clipboard is entirely your decision; BAKLOG never auto-sends it.

### Portable secret bundle

The Connections page (⋮ menu → **Portable bundle…**) includes **Export
bundle…** / **Import bundle…** for moving every connection to another machine
or recovering from a corrupted OS keychain.

| What | Where | Why |
|------|-------|-----|
| Encrypted bundle file | Wherever *you* save it (USB, cloud folder, email to yourself) | One-file backup of all connections |
| Bundle passphrase | Your memory — **not stored by BAKLOG** | Unlocks the bundle; separate from the optional local master password |

The bundle (`baklog-secrets-<timestamp>.bundle`) contains:

- The encrypted credentials document (`cache/auth/secrets.bin` contents, as
  JSON inside the bundle ciphertext).
- Chrome/Edge browser profile directories under `cache/auth/profiles/<store>/` (CDP)
  (cookie-based providers such as GOG and PSN).

It is **always encrypted with its own passphrase** (minimum 8 characters) using
scrypt + AES-GCM. The local OS keychain / master-password key never leaves
your machine. Losing the bundle passphrase means the file cannot be recovered
— there is no reset path.

Import moves any existing `cache/auth/profiles/` tree to
`cache/auth/profiles_pre_import_<timestamp>/` before overwriting, so a bad
import can be rolled back manually.

CLI equivalent:

```bash
python -m auth export-bundle --out baklog-secrets.bundle
python -m auth import-bundle baklog-secrets.bundle
python -m auth import-bundle baklog-secrets.bundle --dry-run
```

The bundle never leaves your machine unless **you** copy it somewhere. BAKLOG
does not upload it.

## What goes over the network

When you click **Refresh** or run a fetcher manually, BAKLOG contacts only the
following services with your credentials. Each call is a direct request from
your machine to the storefront — there is no project-owned middleman.

| Service | Why |
|---------|-----|
| `api.steampowered.com`, `store.steampowered.com` | Steam library, wishlist, reviews, store search |
| `embed.gog.com`, `api.gog.com` | GOG library + wishlist |
| `m.np.playstation.com`, `web.np.playstation.com`, `ca.account.sony.com` | PSN library, trophies, wishlist |
| `www.epicgames.com`, `graphql.epicgames.com`, `account.epicgames.com` | Epic library + wishlist |
| `account.battle.net` | Battle.net library |
| `account.ubisoft.com`, `store.ubisoft.com` | Ubisoft library + wishlist |
| `accounts.nintendo.com`, `ec.nintendo.com` | Nintendo eShop library (transactions cookie) |
| `www.nintendo.com` | Nintendo Store wishlist (`nintendo_wishlist` browser profile) |
| `www.humblebundle.com` | Humble library API + store wishlist (`humble` browser profile) |
| `www.ea.com`, `service-aggregation-layer.juno.ea.com` | EA App library — replays your own ea.com web session via the `ea` browser profile |
| `api.openxbl.com` | Xbox library + wishlist |
| `itch.io` | itch.io library |
| `gaming.amazon.com` | Amazon Prime Gaming (local SQLite — no remote call) |
| `howlongtobeat.com` | HLTB enrichment |
| `api.isthereanydeal.com` | ITAD pricing |

Cover-art enrichment (`enrich_cross_store_images.py`) hits Steam's CDN. The
inline Add-game flow hits `store.steampowered.com/api/storesearch/`.

## What does *not* happen

- No telemetry, analytics, crash reports, or pings home — including the
  error log: it stays in your browser until *you* explicitly copy it via
  the "Copy bug bundle" button.
- No third-party ad/affiliate scripts (the deal links go straight to the store
  via ITAD).
- No project-owned cloud service.
- No automatic sync between machines — use the portable secrets bundle
  (Connections → Export bundle…) if you move to a new PC.

## Removing your data

Everything is on disk:

- `data/personal.json` — your annotations.
- `data/personal_backups/` — rotated backups of the above.
- `games_*.json`, `itad_prices.json`, `data/games_backups/` — fetched
  libraries and their rotated backups.
- `cache/` — CDP browser profiles, fetcher caches, OAuth refresh tokens.
- `cache/auth/profiles_pre_import_*` — snapshots taken before a bundle import.
- `.env` — API keys + session cookies.
- Browser `localStorage` for whatever origin you served the app from
  (typically `http://127.0.0.1:<port>`).

Delete the folders above to remove everything. To rotate or revoke individual
credentials, do it on the storefront's account page and then drop the matching
file in `cache/` / row in `.env`.

## Threat model

For the attacker's-eye view — assets, trust boundary, the cryptography behind
the at-rest and portable-bundle encryption, and an explicit list of what is
**not** defended (local malware, plaintext `.env`, the `.master_key`
fallback, storefront ToS) — see [SECURITY.md](SECURITY.md).

## Reporting a security issue

Email the project author at the address listed in `pyproject.toml` if you find
an issue that would expose someone else's data. Issues that only affect your
own local files are best filed as regular GitHub issues.
