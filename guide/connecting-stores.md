# Connecting stores

Connect each store from the **Connections** tab in the dashboard, then run fetchers from the **Fetcher health** row or from the terminal.

**Recommended flow:** run `python server.py`, open **Connections**, click **Connect** for each store. A headed Chrome/Edge window opens for cookie or OAuth sign-in (if neither is installed, BAKLOG downloads a one-time browser on first Connect). Credentials stay local in encrypted per-profile storage (`cache/auth/`). After connecting, click the matching chip in **Fetcher health** or run the script below.

BAKLOG supports **19 store connections** across **12 libraries** and **8 wishlists** (27 fetcher jobs). Wishlist JSON files are optional per store - the **Fetcher health** row marks any file not yet fetched as *missing*; that is normal until you run the matching script.

## Fetcher options (all scripts)

| Flag | Effect |
|------|--------|
| `--refresh` | Ignore cache, refetch everything (Shift+click on supported library/wishlist chips) |
| `--retry-misses` | Re-attempt enricher rows cached as no match (Shift+click on HLTB, Reviews, Covers) |
| `--only-new` | Only fetch games not already in the store JSON file |
| `--skip-hltb` | Skip HowLongToBeat lookups (faster) |
| `--allow-empty` | Allow writing a zero-item result (default: refuse and exit 2 so stale data is preserved) |

Store-specific flags: `--appid`, `--id`, `--source`, etc.

**Exit codes:** `0` success · `1` runtime/config error · `2` suspicious empty result · `3` drift guard refused write · `4` auth failure. See [Refresh and enrichment](refresh-and-enrichment.md#exit-codes).

First Steam run may take several minutes for a large library (Store API is rate-limited). Subsequent runs use cache and are much faster.

---

## Steam

**Connections:** Steam → **Connect** (grabs your API key automatically).

**Privacy:** set **Game details** to **Public** in Steam → Profile → Edit Profile → Privacy Settings.

**CLI fallback:** set `STEAM_API_KEY` + `STEAM_ID` in `.env`.

```bash
python fetch_games.py
```

Writes `games_steam.json`.

---

## GOG

Two sources, one `games_gog.json`:

| Source | Connections card | When to use |
|--------|------------------|-------------|
| **Galaxy (local)** | GOG Galaxy (launcher) | Richest data from `galaxy-2.0.db` (Windows ProgramData or macOS Shared). Optional: `GOG_GALAXY_DB=`. No Linux path - use web below. |
| **Web** | GOG (web) | Any OS; sign in at gog.com for library + wishlist cookie. |

`fetch_gog.py` picks **auto**: Galaxy DB when present, else the saved web session. Override with `--source local|web` or `GOG_SOURCE=`.

```bash
python fetch_gog.py
python fetch_gog_wishlist.py    # optional - needs GOG session; until run, WL GOG chip shows "missing"
```

**CLI fallback:** copy the `gog-al` cookie from DevTools → Application → Cookies into `GOG_AL=` in `.env`.

If the web fetch fails with **403 Forbidden**, reconnect GOG on Connections (refreshes the cookie). On Windows/macOS with GOG Galaxy installed, prefer `python fetch_gog.py --source local`.

---

## PlayStation (PSN)

**Connections:** PlayStation → **Connect** and sign in at the PlayStation Store.

**Privacy:** set trophy/game privacy to **Anyone** so the library and wishlist can load.

```bash
python fetch_psn.py
```

**CLI fallback:** open https://ca.account.sony.com/api/v1/ssocookie while logged in and paste the `npsso` token into `PSN_NPSSO=` in `.env`.

---

## Epic (library)

**Connections:** Epic (library) → **Connect** - BAKLOG captures and exchanges the authorization code automatically.

```bash
python fetch_epic.py
```

**CLI fallback:** run `python fetch_epic.py --auth-help` and paste the code into `EPIC_AUTH_CODE=` in `.env`.

---

## Epic (wishlist)

Separate session from library OAuth. **Connections:** Epic (wishlist) → **Connect** at [store.epicgames.com/wishlist](https://store.epicgames.com/en-US/wishlist) (clear Cloudflare if shown). `fetch_epic_wishlist.py` reuses the saved browser profile headlessly.

```bash
python fetch_epic_wishlist.py
```

---

## Amazon Games

Two sources, one `games_amazon.json`:

| Source | Connections card | When to use |
|--------|------------------|-------------|
| **Launcher (Windows)** | Amazon Games (launcher) | Richest data (art, last played) from local SQLite. Optional: `AMAZON_GAMES_SQL_DIR=`. |
| **Prime Gaming (web)** | Amazon (Prime Gaming, web) | Any OS; imports Amazon-fulfilled claims only (skips Epic/Steam key drops). |

`fetch_amazon.py` picks **auto**: launcher DB on Windows when present, else the saved web session. Override with `--source launcher|web` or `AMAZON_SOURCE=`.

```bash
python fetch_amazon.py
python fetch_amazon.py --source web --dump-raw   # debug: writes cache/amazon_web_raw.json
```

On macOS/Linux, use the Prime Gaming web card + `--source web` (launcher DB is Windows-only).

---

## Xbox (play history)

**Connections:** Xbox → **Connect** at [xbl.io](https://xbl.io/login), or paste an OpenXBL API key into the card.

```bash
python fetch_xbox.py --skip-hltb
```

---

## Xbox Store wishlist

Separate from play history. **Connections:** Xbox Store wishlist → **Connect** on xbox.com.

```bash
python fetch_xbox_wishlist.py
```

---

## Battle.net (unofficial)

**Connections:** Battle.net → **Connect** and sign in at [account.battle.net](https://account.battle.net/). The managed browser saves your session cookie locally.

```bash
python fetch_battlenet.py --skip-hltb
```

**CLI fallback:** DevTools → Network → `games-and-subs` → copy the full `Cookie:` header into `BATTLENET_COOKIE=` in `.env`, then `python fetch_battlenet.py --browser env --skip-hltb`. On Windows, Edge/Chrome v127+ app-bound encryption can block the legacy fetch-time browser-jar read; Connect + stored cookie avoids that. Firefox (`--browser firefox`) or the `.env` cookie path still work without admin.

---

## Ubisoft Connect (unofficial)

**Connections:** Ubisoft Connect → **Connect** (one sign-in for library + Ubisoft Store wishlist).

```bash
python fetch_ubisoft.py --skip-hltb
python fetch_ubisoft_wishlist.py
```

**CLI fallback:** DevTools → Network → `public-ubi` → copy `Authorization` and `Ubi-SessionId` into `.env`.

---

## Nintendo (eShop library)

**Connections:** Nintendo → **Connect**. Only ~2 years of digital eShop history; cartridge games and older purchases must be added manually.

```bash
python fetch_nintendo.py --skip-hltb
```

**CLI fallback:** copy the `Cookie` header from a `ec.nintendo.com/my/transactions` request into `NINTENDO_COOKIE=` in `.env`.

---

## Nintendo Store wishlist

**Connections:** Nintendo Store wishlist → **Connect** on nintendo.com (separate from eShop library login).

```bash
python fetch_nintendo_wishlist.py
```

---

## EA App

**Connections:** EA App → **Connect** at ea.com.

```bash
python fetch_ea.py
```

---

## Humble Bundle

**Connections:** Humble Bundle → **Connect** at humblebundle.com (library page). One profile unlocks library + store wishlist fetchers.

```bash
python fetch_humble.py --skip-hltb
python fetch_humble_wishlist.py
```

---

## itch.io

Two sources, one `games_itch.json`:

| Source | Connections card | When to use |
|--------|------------------|-------------|
| **Butler (local)** | itch butler (local) | Owned library + playtime from the itch app's `butler.db` (Windows / macOS / Linux). No API key required when the DB is present. |
| **API** | itch.io (API key) | Richer metadata (publisher, full tag lists). API key from https://itch.io/user/settings/api-keys → `ITCH_API_KEY=` in `.env` or Connections. |

`fetch_itch.py` picks **auto**: butler.db when present, else the API key. Override with `--source local|api` or `ITCH_SOURCE=`.

```bash
python fetch_itch.py --skip-hltb
python enrich_steam_reviews.py --stores itch
```

Writes all owned keys (games + tools/TTRPG PDFs). The dashboard itch.io tab hides non-games by default.

---

## Wishlist and deal prices

```bash
python fetch_wishlist.py --skip-hltb          # Steam wishlist
python fetch_gog_wishlist.py                # GOG (needs GOG session)
python fetch_epic_wishlist.py
python fetch_nintendo_wishlist.py
python fetch_humble_wishlist.py
python fetch_itad.py                        # IsThereAnyDeal prices → itad_prices.json
```

**Display currency / FX:** set `ITAD_COUNTRY` (e.g. `GB`) before `fetch_itad.py`. ITAD and wishlist rows use that region's currency. The script caches daily exchange rates from [Frankfurter](https://www.frankfurter.app/) and writes comparable `price_amount` fields on wishlist JSON while keeping `price_native` / `currency_native` for the store's real price. Re-run ITAD after wishlist fetches to refresh conversions.

**Wishlist deal UI:** Cross-store deal prices on the Wishlist tab and Dashboard require **ITAD** connected in Connections (validated API key) plus a run of `fetch_itad.py` from Fetcher health.

---

## Platform availability

| Store | Windows | macOS / Linux |
|-------|:-------:|:-------------:|
| Steam, GOG (web), PSN, Epic, Xbox, Battle.net, Ubisoft, Nintendo, itch.io, Humble, EA, ITAD | Yes | Yes |
| Amazon (Prime Gaming, web) | Yes | Yes |
| GOG Galaxy (local `galaxy-2.0.db`) | Yes | macOS only (no Linux Galaxy path) |
| itch butler (local `butler.db`) | Yes | Yes |
| Amazon Games (launcher DB) | Yes | No |

Platform-restricted local providers show as **Unavailable** on unsupported OSes; their fetcher chips stay enabled when a web fallback exists.

See also [Troubleshooting](troubleshooting.md) for auth failures, 403 errors, and empty results.
