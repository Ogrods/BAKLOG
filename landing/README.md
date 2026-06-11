# BAKLOG landing page

Static blue-on-blue landing page with an email waitlist, deployed to Vercel.

## Files

- `index.html` — page markup, inline base CSS, waitlist form shell. No build step.
- `structured-data.json` — JSON-LD for crawlers (loaded externally for CSP compliance).
- `main.js` — footer year, non-blocking font load, waitlist submit handler.
- `demo.css` — mega hero dashboard styles (spotlight, marquee, ribbon charts, funnel sections).
- `demo.js` — interactive demo (dummy data, count-up, spotlight rotation, Chart.js donuts).
- `assets/sample/*.{webp,png}` — fictional game covers for the spotlight carousel.
- `api/subscribe.js` — Vercel serverless function; logs signups (optional Supabase), emails you via [Resend](https://resend.com), and sends the signer a confirmation auto-reply.
- `api/_rate-limit.js` — shared distributed rate limiter (Vercel KV / Upstash) used by `subscribe.js`.
- `package.json` — Upstash deps for serverless `api/` functions (`npm install` inside `landing/`).
- `api/report.js` — Vercel serverless function; receives opt-in bug reports from the local app, logs them (optional Supabase), and emails you via Resend. Reuses the same `RESEND_*` / `SUPABASE_*` env vars as `subscribe.js`.
- `api/metrics.js` — Vercel serverless function; receives opt-in anonymous aggregate metrics from the local app (session counts + sponsored-slot impressions/clicks). Optional Supabase log via `sql/aggregate_metrics.sql`.
- `sql/waitlist.sql` — one-time Supabase table for durable signup logging.
- `sql/bug_reports.sql` — one-time Supabase table for durable bug-report logging.
- `assets/og.png` — 1200×630 social share image (rendered from the real logo by `../tools/make_og_image.py`).
- `assets/store-logos/*.svg` — copy of repo-root `assets/store-logos/` for the hero trust strip (CSS mask). Re-sync when app logos change: `cp ../assets/store-logos/*.svg assets/store-logos/`.
- `favicon.svg` — white BAKLOG mark.
- `apple-touch-icon.png` — 180×180 home-screen icon (`../tools/make_apple_touch_icon.py`).
- `404.html` — branded not-found page (Vercel serves automatically).
- `free-claims.json` — built by `build_free_claims.py` at repo root; hosted feed for Claimable Now.
- `sponsors.json` — sponsored/house deal slots for the local app; sync from `curated/sponsors.json` before deploy.
- `vercel.json` — CSP, security + cache headers, clean URLs.

## Deploy to Vercel

1. Import this Git repo in Vercel.
2. **Set the project Root Directory to `landing`** (Settings → Build & Development → Root Directory).
   - Framework Preset: **Other**. No build command. Output is served as static + `api/` functions.
3. Add the environment variables below (Settings → Environment Variables), then redeploy.
4. Point your domain at the project (Settings → Domains).

## Environment variables

The waitlist function needs three vars (all environments):

| Variable | Example | Notes |
| --- | --- | --- |
| `RESEND_API_KEY` | `re_xxxxxxxx` | From Resend → API Keys. |
| `NOTIFY_FROM` | `BAKLOG <waitlist@baklog.app>` | Sender must be on a **Resend-verified domain** (verify `baklog.app` in Resend → Domains). |
| `NOTIFY_TO` | `you@baklog.app` | Where signup notifications land. `reply_to` is set to the signup's email. |

Optional durable logging (recommended):

| Variable | Example | Notes |
| --- | --- | --- |
| `SUPABASE_URL` | `https://xxxx.supabase.co` | Project URL (same project as BAKLOG auth is fine). |
| `SUPABASE_SERVICE_ROLE_KEY` | `eyJ...` | **service_role** key from Project Settings → API. Server-only; never expose in the browser. |

Run `sql/waitlist.sql` once in the Supabase SQL editor before enabling these vars. Without Supabase env vars, signups still work; they are only emailed and logged to Vercel function logs.

Without the Resend trio, `/api/subscribe` returns `500 Server not configured` and the form shows a friendly error.

## Rate limiting (required for production)

`/api/subscribe` rate-limits by client IP (5 requests per minute). Production uses a **distributed** store so limits survive Vercel cold starts and scale-out. Without KV credentials in production, `/api/subscribe` returns `503 Server not configured`.

1. Vercel project (root `landing/`) → **Storage** → **Create Database** → **KV** → connect to this project.
2. Redeploy so Production receives the auto-injected credentials below.
3. Smoke test: POST `/api/subscribe` six times from the same IP — the sixth should return `429 Too many requests`.

| Variable | Notes |
| --- | --- |
| `KV_REST_API_URL` | Auto-injected when Vercel KV is linked to the project. |
| `KV_REST_API_TOKEN` | Auto-injected when Vercel KV is linked to the project. |

Alternatively, set `UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_REST_TOKEN` from a standalone Upstash Redis database.

Local `vercel dev` and Vitest fall back to an in-memory limiter when KV vars are absent (with a one-time console warning). Install landing API deps once: `npm install` inside `landing/`.

## Local preview

Static preview (form will fail without the API, which is expected). **Serve from `landing/`** so `demo.css`, `demo.js`, and sample covers load:

```sh
# from the repo root (recommended)
npm run landing
# open http://localhost:4000

# or from the landing/ folder
python -m http.server 4000
# open http://localhost:4000
```

If you serve from the repo root without `--directory landing`, open `http://localhost:PORT/landing/` (relative asset paths resolve from that URL).

Full preview incl. the function:

```sh
npm i -g vercel
vercel dev   # run from landing/  (uses .env / Vercel env)
```

## Claimable Now feed (`free-claims.json`)

The local app and read-only mode pull a maintainer-curated list of free giveaways from `https://baklog.app/free-claims.json`. The feed aggregates active giveaways from Epic, GamerPower, and IsThereAnyDeal (Epic, GOG, Steam, Prime, and more). This file is **not** built by Vercel — you publish it from the repo:

0. Run `python fetch_claim_sources.py` (optionally `--dry-run`) to refresh auto-discovered claims from Epic, GamerPower, and ITAD giveaways RSS into `curated/free_claims.auto.json`. Epic is the most reliable source; GamerPower and ITAD broaden coverage for GOG/Steam and other stores. **GamerPower requires attribution** — the published feed includes `"attribution": ["GamerPower.com"]` when any GamerPower item is included.
1. Edit `free-claims.input.json` at the repo root (add/update manual `items` with `id`, `store`, `title`, `claim_url`, optional `ends_at`, `steam_appid`, `notes`). Manual entries always win over auto-sourced duplicates.
2. Run `python build_free_claims.py` — merges manual + auto items, Steam-enriches entries, and writes:
   - `landing/free-claims.json` (hosted on Vercel)
   - `curated/free_claims.fallback.json` (bundled offline fallback)
   - active profile `free_claims.json` (local app picks this up immediately; use `--no-profile` to skip)
3. Commit and deploy `landing/` (or copy `landing/free-claims.json` to production).

Other machines pull the hosted feed via **Prices → Free** or `python fetch_free_claims.py` (also in `refresh.ps1` / `refresh.sh` after ITAD).

## Sponsored deal feed (`sponsors.json`)

The local app loads disclosed sponsored/house deal slots from `https://baklog.app/sponsors.json` when the profile has no local override. Offline or when the hosted feed is unreachable, the bundled `curated/sponsors.json` in the app package is the last-known-good fallback.

**Resolution order in the app:** profile `sponsors.json` (admin/local override) → hosted `sponsors.json` → bundled `curated/sponsors.json`.

### Maintainer workflow

1. Edit campaigns in `curated/sponsors.json` at the repo root, or via the admin console (`BAKLOG_ADMIN=1` → `/api/internal/sponsors`).
2. Copy the same file to `landing/sponsors.json` (keep them in sync before deploy):

   ```sh
   cp curated/sponsors.json landing/sponsors.json
   ```

3. Commit and deploy `landing/` so Vercel serves the updated feed (~10 min CDN TTL via `vercel.json`).

Feed schema:

```json
{
  "version": 1,
  "generated_at": "2026-06-09T00:00:00Z",
  "items": [{
    "id": "aff-fanatical-weekend",
    "kind": "sponsor",
    "title": "Weekend Sale",
    "tagline": "Up to 90% off",
    "cta": "Shop deals",
    "url": "https://www.fanatical.com/?ref=YOUR_TAG",
    "cover": "/assets/ads-sample/cover-encore.webp",
    "placements": "picks",
    "priority": 2,
    "enabled": true,
    "starts": "2026-06-09T00:00:00Z",
    "ends": "2026-06-16T00:00:00Z",
    "network": "fanatical"
  }]
}
```

- `kind: "house"` → **House** disclosure (BAKLOG promos). Anything else → **Sponsored** (affiliate or paid placement).
- `placements`: `deal-rail`, `dash-deal-rail`, `spotlight`, `picks`, `table`, `dash-picks`, `dash-versus`, `coop-online`, `coop-couch`, `claimable` (comma string or array).
- `match_title`: skip the slot when the user already owns that game.
- `network`: optional bookkeeping field (ignored by the app; useful for your records).
- Steam has no affiliate program.

### Affiliate monetization (two paths)

**1. Sponsored feed (high-commission marketplaces)** — Fanatical, Green Man Gaming, and similar shops that only appear as ITAD *deal* links are monetized here. Add a creative with your tagged affiliate URL; clicks open `url` via the existing sponsored-deal handler (no extra app code). Example v2 creative:

```json
{
  "ads": {
    "aff-fanatical-weekend": {
      "kind": "sponsor",
      "title": "Fanatical Weekend Sale",
      "tagline": "Up to 90% off PC keys",
      "cta": "Shop deals",
      "url": "https://www.fanatical.com/?ref=YOUR_TAG",
      "cover": "/assets/ads-sample/cover-encore.webp",
      "enabled": true,
      "starts": "2026-06-09T00:00:00Z",
      "ends": "2026-06-16T00:00:00Z",
      "network": "fanatical"
    }
  },
  "locations": {
    "wish-pick": ["aff-fanatical-weekend"],
    "dash-pick": ["aff-fanatical-weekend"]
  }
}
```

Copy `curated/sponsors.json` → `landing/sponsors.json` and deploy.

**2. Store-page links (`js/affiliate.js`)** — When you open a game on its *library store* (GOG, Epic, Humble rows), BAKLOG builds the URL in `storeUrlForGame` and may append your tag. Edit `AFFILIATE_RULES` in `js/affiliate.js`: fill `value` (param mode) or `template` (deeplink mode with `{url}`), set `enabled: true`. Rules ship disabled so links are untouched until you enroll.

**ITAD deal links are NOT tagged** — wishlist "best deal" URLs are `next.isthereanydeal.com` redirects that already carry ITAD's affiliate tag; the ITAD API ToS forbids altering them.

No per-user impression or click tracking is sent from the app unless the user opts in (see below); affiliate networks attribute revenue from the tagged URL only.

### Affiliate signup checklist

| Program | Enroll via | What you get | Where it goes | Terms (verify on signup) |
|---------|------------|--------------|---------------|--------------------------|
| **GOG** | affiliate@gog.com + [AdTraction](https://adtraction.com) | Deeplink template or `af.gog.com` branded link | `js/affiliate.js` GOG rule `template` **and/or** sponsor creative `url` | 6% net, 7-day cookie |
| **Epic** | [Support-A-Creator](https://sac.epicgames.com/overview) | Creator tag | `js/affiliate.js` Epic rule `value` (`epic_creator_id`) | 5% min, $100 payout floor |
| **Humble** | [Impact](https://impact.com) | Deeplink template | `js/affiliate.js` Humble rule `template` **and/or** sponsor creative | ~5.6%+, 30-day |
| **Fanatical** | CJ Affiliate / Awin | `?ref=` tag or deeplink | **Sponsor feed only** (`curated/sponsors.json`) | Up to 5%, 30-day |
| **Green Man Gaming** | Awin | Deeplink template | **Sponsor feed only** | 5% new / 2% returning |
| **Gamesplanet** | partners@gamesplanet.com | `?ref=` tag | **Sponsor feed only** (gated ~4k followers) | 5–10% |
| **ITAD** | Contact ITAD re: official app / partner status | Revenue share on organic deal clicks | N/A today — only legit path to ITAD redirect revenue | API ToS invites contact |

## Opt-in aggregate metrics (`/api/metrics`)

Users can optionally enable **Share anonymous usage counts** in the app (Connections → automatic fetch preferences). When enabled, the app POSTs batched anonymous totals to `https://baklog.app/api/metrics` every ~5 minutes and on tab close:

- `session_start` — one per app launch (active-user proxy)
- `impression` — sponsored-slot views (deduped per placement per session)
- `click` — sponsored-slot outbound clicks

**Nothing is sent when the toggle is off** (default). No IP is stored server-side; payloads carry only `app_version`, an opaque per-launch `session_id`, and event counts. Optional durable logging: run `sql/aggregate_metrics.sql` in Supabase and set `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` (same as `/api/report`). Production rate limiting uses the same Vercel KV / Upstash credentials as `/api/subscribe` (namespace `metrics`).

## Regenerate share / touch icons

```sh
python tools/make_og_image.py          # run from the repo root; writes landing/assets/og.png
python tools/make_apple_touch_icon.py  # writes landing/apple-touch-icon.png
```
