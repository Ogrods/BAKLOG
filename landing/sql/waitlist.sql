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
-- No policies: anon/public have no access; service_role bypasses RLS.
