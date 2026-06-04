# Supabase invite-only login

BAKLOG can require a Supabase account before the dashboard loads. Each signed-in user gets an isolated profile directory under `profiles/<user-id>/` (games JSON, personal data, Connections secrets).

## 1. Create a Supabase project

1. Sign in at [supabase.com](https://supabase.com) and create a project.
2. **Authentication → Providers → Email:** enable Email; turn **off** "Enable email signups" (invite-only).
3. **Authentication → Users → Invite user** for each person. They receive an email to set a password.
4. **Project Settings → API:** copy:
   - **Project URL** → `BAKLOG_SUPABASE_URL`
   - **anon public** key → `BAKLOG_SUPABASE_ANON_KEY` (safe in the browser)
   - **JWT Secret** (optional, legacy HS256) → `BAKLOG_SUPABASE_JWT_SECRET` — server only; never commit or expose in the browser. Newer projects can omit this; the server verifies asymmetric tokens via the project JWKS endpoint automatically.
5. **Authentication → URL configuration:** set **Site URL** to where you open BAKLOG (e.g. `http://127.0.0.1:8765`). Add the same URL under **Redirect URLs** if you use magic links later.

Optional: configure custom SMTP under **Authentication → Email templates** for branded invite mail.

## 2. Configure BAKLOG

Add to `.env` (see `.env.example`):

```env
BAKLOG_SUPABASE_URL=https://xxxx.supabase.co
BAKLOG_SUPABASE_ANON_KEY=eyJ...
# Optional legacy HS256 verification (omit on JWKS-only projects):
# BAKLOG_SUPABASE_JWT_SECRET=your-jwt-secret
```

Restart `python server.py`. The login overlay appears when URL + anon key are set.

**Local dev without Supabase:** set `BAKLOG_AUTH_DISABLED=1` in `.env` to skip JWT checks and use the normal profile switcher.

## 3. Migrate your existing library (optional)

Your pre-auth data may live in `profiles/default/` or the repo root (legacy layout). Supabase users do **not** auto-link to `default`. To attach old data to your account:

1. Sign in once and note your user UUID (Supabase dashboard → Authentication → Users, or decode the JWT `sub` claim).
2. Copy your library tree into `profiles/<your-uuid>/` (including `data/`, `games_*.json`, `cache/auth/` if needed).
3. Reload the app.

## 4. Session probe vs Connections status

- **`GET /api/auth/session`** — lightweight account check (`{ ok, email, profile }`). The login overlay uses this to confirm the JWT before boot continues.
- **`GET /api/auth/status`** — **Connections** provider state (Steam, GOG, etc.), not Supabase login.

## 5. SSE stream tickets

`EventSource` cannot send an `Authorization` header. When auth is on:

1. The browser calls `POST /api/auth/stream-ticket` with a valid Bearer (via `baklogFetch`).
2. The server returns a single-use `ticket` (30s TTL) bound to that user's profile.
3. Connections and fetcher log streams open as `GET /api/auth/<id>/stream?ticket=…` or `GET /api/stream/<run_id>?ticket=…`.

Tickets are redacted in server access logs.

## 6. Launch model (single-user self-host)

Each person runs their own `python server.py`. The gate is invite-only access control: one signed-in account per process, with data under `profiles/<user-id>/`.

**Phase 6 (post-launch, shared server):** per-user `active.json` / `queue.json`, full multi-tenant run isolation, and auth-SSE session ownership beyond profile scoping — only needed when one server process serves multiple Supabase users at once (tunnel / cloud mirror work).

## 7. Security model (when auth is enabled)

- **App shell** (`index.html`, `js/`, `css/`) is public so the login page can load.
- **Catalog + cache JSON** (`games_*.json`, `itad_prices.json`, whitelisted `cache/*.json`) require a valid Supabase Bearer token and are served from **that user's** `profiles/<user-id>/` tree only.
- **Sensitive paths** (`.env`, `data/`, `cache/auth/`, `profiles/`) return 404 always — even without auth enabled.
- **API writes** accept a valid Bearer as CSRF-safe when auth is on (so tunnels work); localhost header/origin rules still apply when auth is off.
- Game libraries and store credentials stay **on your machine** under `profiles/<user-id>/`. Supabase stores account email and auth metadata only.
- `server.py` still binds to `127.0.0.1` by default. Enabling Supabase auth makes the app **safe to expose** (tunnel/reverse proxy) from a data-isolation standpoint; actually exposing the server remains an operational choice (see tracker Phase 6).
