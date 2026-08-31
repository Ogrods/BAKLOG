# Profiles and moving machines

Separate datasets for work vs play, optional PINs, and moving credentials to a new PC.

## Local profiles

Use the **profile menu** in the header (next to the logo) for separate datasets. Until you add a second profile, everything stays in the repo root.

**Create a profile:**

1. Open the profile menu → **Manage profiles**.
2. Enter a name (e.g. Work) and click **Create**.

The first **Create** copies your current `games_*.json`, `data/`, and `cache/auth/` into `profiles/default/` (root files remain as backup) and starts the new profile empty.

Each profile keeps its own library, connections, and personal data under `profiles/<name>/`. Switching profiles reloads the app.

**CLI fetchers** respect `BAKLOG_PROFILE=<id>` or the active entry in `profiles/index.json`:

```powershell
$env:BAKLOG_PROFILE='work'; python fetch_games.py
```

The dev server **auto-ignores** `BAKLOG_PROFILE` in its own shell at startup so the menu always owns the active profile. Per-run fetchers from the UI still pin the correct profile.

**Rollback:** delete the `profiles/` folder to return to legacy single-root layout.

## Optional PINs

When Supabase sign-in is enabled, set `BAKLOG_LOCAL_PROFILES=1` to keep the local Work/Play profile switcher available. Optional per-profile PINs gate switching; profile mutations require the in-app local header.

## New profile defaults

New profiles opt out all **local** providers (Amazon launcher, GOG Galaxy, itch butler) until you explicitly Connect on that profile. This prevents a fresh profile from pulling machine-wide launcher databases you didn't intend to share.

Profile switch cancels in-flight fetchers, resets secrets cache, rebinds run paths, and blocks switch while a browser sign-in is active.

## Moving to a new machine

### Credentials (Connections)

1. **Old machine:** **Connections** → ⋮ → **Portable bundle…** → **Export bundle…**. Choose a passphrase and save the downloaded `baklog-secrets-*.bundle` somewhere safe (USB, cloud folder, etc.).

2. **New machine:** Install BAKLOG (`pip install -r requirements.txt`, `python server.py`). Chrome or Edge is preferred for Connections; if missing, first Connect downloads a one-time browser (~150 MB).

3. **New machine:** **Connections** → ⋮ → **Portable bundle…** → **Import bundle…**, pick the file, enter the same passphrase. The page reloads with every provider restored - including browser cookie profiles.

**Terminal alternative:**

```bash
python -m auth export-bundle --out baklog-secrets.bundle
python -m auth import-bundle baklog-secrets.bundle
```

See [PRIVACY.md](../PRIVACY.md#portable-secret-bundle) for bundle contents and [SECURITY.md](../SECURITY.md) for the threat model.

### Library and personal data

On Windows beta installs, library data lives in `%LOCALAPPDATA%\BAKLOG-Data`
(profiles, `games_*.json`, connections, personal edits). The app itself installs
to `%LOCALAPPDATA%\BAKLOG`. Back up or copy the **data** folder when moving
machines. Override with `BAKLOG_DATA_DIR` if you use a custom location.

Copy these folders/files to the new machine (or sync via Dropbox/OneDrive):

- `games_*.json`, `itad_prices.json` (or `profiles/<id>/` equivalents)
- `data/personal.json` (statuses, notes, priorities, tags)
- `profiles/` if you use multi-profile mode

Re-run fetchers on the new machine to refresh stale data, or copy `cache/` to skip re-downloading API responses.

## Optional account sign-in

When configured, account sign-in can require a login before the dashboard loads; each user gets their own profile data directory. Set `BAKLOG_SUPABASE_URL` and `BAKLOG_SUPABASE_ANON_KEY` in `.env` (see `.env.example`). Without those env vars, local behavior is unchanged. Use `BAKLOG_AUTH_DISABLED=1` to skip the gate while testing.
