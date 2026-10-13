-- BAKLOG Pro purchases that matched no account yet (run once in the Supabase SQL editor).
-- web/api/polar-webhook.js upserts a row here when a Polar buyer has no BAKLOG
-- account with the checkout email (or external id). web/api/auth-signup-notify.js
-- applies the plan when an account with that email is created, then stamps
-- applied_at. Only the service_role (Vercel functions) may read or write it.

create table if not exists public.polar_pending_entitlements (
  email text primary key check (email = lower(email)),
  plan text not null check (plan in ('pro', 'free')),
  last_event_type text not null default '',
  polar_customer_id text not null default '',
  polar_subscription_id text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  applied_at timestamptz,
  applied_user_id uuid
);

alter table public.polar_pending_entitlements enable row level security;

-- No policies: anon/authenticated get nothing; service_role bypasses RLS.
revoke all on table public.polar_pending_entitlements from public, anon, authenticated;
grant select, insert, update on table public.polar_pending_entitlements to service_role;
