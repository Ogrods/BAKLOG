# Supabase SQL (manual apply)

These scripts are applied by hand in the Supabase SQL editor. There is no CI migrate step. Keep this folder and `manifest.json` in sync when you change a script.

## Apply order

1. `waitlist.sql` - landing waitlist + beta invite columns
2. `bug_reports.sql` - opt-in bug report rows
3. `aggregate_metrics.sql` - opt-in anonymous aggregate metrics
4. `polar_entitlement.sql` - email → user id RPC for Polar webhooks
5. `polar_pending_entitlements.sql` - Polar purchases waiting for account signup
6. `cloud_mirror.sql` - Pro cloud mirror bucket + RLS

Most statements use `if not exists` / `on conflict` so re-running a file is usually safe. Prefer re-running the single changed file after a revision bump.

## Revisions

Each file starts with `-- baklog-sql-revision: YYYY-MM-DD`. The same dates are listed in `manifest.json`. When you edit a script, bump that date in both places and note the live revision in private `baklog-internal/tracker.html`.
