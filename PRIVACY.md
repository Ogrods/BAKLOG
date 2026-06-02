# Privacy

BAKLOG is a **local-only** desktop tool. It does not have a server, account
system, telemetry, or analytics. The "server" referenced in the README is a
`http://127.0.0.1` Python process that exists only to serve files to your own
browser tab. Nothing leaves your machine except direct calls you make to the
storefronts and enrichment services listed below.

Last updated: 2026-06-01.

## TL;DR

- Everything is stored locally on your computer.
- BAKLOG talks to each storefront on your behalf using the credentials you
  provide. Each storefront sees its own normal API/scrape traffic from you.
- We have no servers, so we cannot collect data even if we wanted to. The
  authors never receive your library, wishlist, notes, or credentials.
- Backups of your personal data and fetched libraries are written locally and
  not transmitted anywhere.

## What is stored, where, and why

### Credentials
| What | Where | Why |
|------|-------|-----|
| OAuth refresh tokens (Epic, Battle.net, Nintendo) | `cache/<store>/session.json` and/or the OS keychain via Python `keyring` | Re-auth without re-prompting |
| Session cookies (GOG, PSN NPSSO, Xbox, Ubisoft, itch, Epic storefront) | `.env` and/or `cache/auth/profiles/<store>/` (Playwright user-data directory) | Same as above |
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
| `accounts.nintendo.com`, `ec.nintendo.com` | Nintendo library |
| `api.openxbl.com` | Xbox library + wishlist |
| `itch.io` | itch.io library |
| `gaming.amazon.com` | Amazon Prime Gaming (local SQLite — no remote call) |
| `howlongtobeat.com` | HLTB enrichment |
| `api.isthereanydeal.com` | ITAD pricing |

Cover-art enrichment (`enrich_cross_store_images.py`) hits Steam's CDN. The
inline Add-game flow hits `store.steampowered.com/api/storesearch/`.

## What does *not* happen

- No telemetry, analytics, crash reports, or pings home.
- No third-party ad/affiliate scripts (the deal links go straight to the store
  via ITAD).
- No project-owned cloud service.
- No background sync between machines (open issue: see
  `bs_secret_recovery` — portable encrypted bundle is on the roadmap).

## Removing your data

Everything is on disk:

- `data/personal.json` — your annotations.
- `data/personal_backups/` — rotated backups of the above.
- `games_*.json`, `itad_prices.json`, `data/games_backups/` — fetched
  libraries and their rotated backups.
- `cache/` — Playwright profiles, fetcher caches, OAuth refresh tokens.
- `.env` — API keys + session cookies.
- Browser `localStorage` for whatever origin you served the app from
  (typically `http://127.0.0.1:<port>`).

Delete the folders above to remove everything. To rotate or revoke individual
credentials, do it on the storefront's account page and then drop the matching
file in `cache/` / row in `.env`.

## Reporting a security issue

Email the project author at the address listed in `pyproject.toml` if you find
an issue that would expose someone else's data. Issues that only affect your
own local files are best filed as regular GitHub issues.
