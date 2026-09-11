-- BAKLOG opt-in aggregate metrics (run once in Supabase SQL editor).
-- Inserts use the service_role key from the Vercel metrics function.
-- No IP or user identifiers are stored.

create table if not exists public.aggregate_metrics (
  id uuid primary key default gen_random_uuid(),
  app_version text not null default 'unknown',
  session_id text not null,
  events jsonb not null,
  created_at timestamptz not null default now()
);

create index if not exists aggregate_metrics_created_at_idx
  on public.aggregate_metrics (created_at desc);

alter table public.aggregate_metrics enable row level security;
grant select, insert on public.aggregate_metrics to service_role;
