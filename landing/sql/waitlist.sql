-- BAKLOG landing waitlist (run once in Supabase SQL editor).
-- Inserts use the service_role key from the Vercel subscribe function.

create table if not exists public.waitlist (
  id uuid primary key default gen_random_uuid(),
  email text not null unique,
  created_at timestamptz not null default now(),
  source text default 'landing',
  ip text
);

alter table public.waitlist enable row level security;
-- Required: service_role must have table grants (RLS alone is not enough).
grant select, insert on public.waitlist to service_role;
-- No policies: anon/public have no access; service_role bypasses RLS.
