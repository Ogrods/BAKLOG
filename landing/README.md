# BAKLOG landing page

Static blue-on-blue landing page with an email waitlist, deployed to Vercel.

## Files

- `index.html` — page markup, inline base CSS, waitlist form shell. No build step.
- `structured-data.json` — JSON-LD for crawlers (loaded externally for CSP compliance).
- `main.js` — footer year, non-blocking font load, waitlist submit handler.
- `demo.css` — mega hero dashboard styles (spotlight, marquee, ribbon charts, funnel sections).
- `demo.js` — interactive demo (dummy data, count-up, spotlight rotation, Chart.js donuts).
- `assets/sample/*.png` — fictional game covers for the spotlight carousel.
- `api/subscribe.js` — Vercel serverless function; logs signups (optional Supabase), emails you via [Resend](https://resend.com), and sends the signer a confirmation auto-reply.
- `api/report.js` — Vercel serverless function; receives opt-in bug reports from the local app, logs them (optional Supabase), and emails you via Resend. Reuses the same `RESEND_*` / `SUPABASE_*` env vars as `subscribe.js`.
- `sql/waitlist.sql` — one-time Supabase table for durable signup logging.
- `sql/bug_reports.sql` — one-time Supabase table for durable bug-report logging.
- `assets/og.png` — 1200×630 social share image (rendered from the real logo by `../tools/make_og_image.py`).
- `assets/store-logos/*.svg` — copy of repo-root `assets/store-logos/` for the hero trust strip (CSS mask). Re-sync when app logos change: `cp ../assets/store-logos/*.svg assets/store-logos/`.
- `favicon.svg` — white BAKLOG mark.
- `apple-touch-icon.png` — 180×180 home-screen icon (`../tools/make_apple_touch_icon.py`).
- `404.html` — branded not-found page (Vercel serves automatically).
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

## Regenerate share / touch icons

```sh
python tools/make_og_image.py          # run from the repo root; writes landing/assets/og.png
python tools/make_apple_touch_icon.py  # writes landing/apple-touch-icon.png
```
