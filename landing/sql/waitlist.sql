-- BAKLOG landing waitlist (run once in Supabase SQL editor).
-- Inserts use the service_role key from the Vercel subscribe function.

create table if not exists public.waitlist (
  id uuid primary key default gen_random_uuid(),
  email text not null unique,
  created_at timestamptz not null default now(),
  source text default 'landing',
  ip text
);

-- Beta invite bookkeeping: set by scripts/send-beta-invites.mjs so waves never
-- double-invite the same signup. Null = not yet invited.
alter table public.waitlist add column if not exists invited_at timestamptz;

alter table public.waitlist enable row level security;
-- Required: service_role must have table grants (RLS alone is not enough).
-- update is needed so the beta-invite script can stamp invited_at.
grant select, insert, update on public.waitlist to service_role;
-- No policies: anon/public have no access; service_role bypasses RLS.
