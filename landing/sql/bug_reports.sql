-- BAKLOG bug reports (run once in Supabase SQL editor).
-- Inserts use the service_role key from the Vercel report function.

create table if not exists public.bug_reports (
  id uuid primary key default gen_random_uuid(),
  app_version text not null default 'unknown',
  ua text,
  view text,
  contact text,
  note text,
  error_count integer not null default 0,
  bundle jsonb not null,
  ip text,
  created_at timestamptz not null default now()
);

alter table public.bug_reports enable row level security;
-- Required: service_role must have table grants (RLS alone is not enough).
grant select, insert on public.bug_reports to service_role;
-- No policies: anon/public have no access; service_role bypasses RLS.
