-- BAKLOG Pro cloud mirror — run once in the Supabase SQL editor.
-- Stores derived catalog JSON per auth user (read-only mirror for signed-in Pro).
-- Credentials, cache/, and secrets never belong in this bucket.
--
-- Re-run the "Pro entitlement" section below on existing projects to replace
-- storage policies that lacked a plan check (post-v0.8.30 audit fix).

-- Private bucket for per-user mirror artifacts (upload via user JWT + Pro claim).
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'baklog-mirror',
  'baklog-mirror',
  false,
  52428800,
  array['application/json']::text[]
)
on conflict (id) do nothing;

-- Mirror metadata (optional complement to Storage object paths).
create table if not exists public.cloud_mirror_snapshots (
  user_id uuid not null references auth.users (id) on delete cascade,
  profile_id text not null default 'default',
  artifact_path text not null,
  revision bigint not null default 1,
  byte_size bigint not null default 0,
  updated_at timestamptz not null default now(),
  primary key (user_id, profile_id, artifact_path)
);

alter table public.cloud_mirror_snapshots enable row level security;

-- JWT plan helper (Pro / paid / premium aliases).
create or replace function public.mirror_is_pro_jwt()
returns boolean
language sql
stable
as $$
  select coalesce(
    auth.jwt()->'app_metadata'->>'plan',
    auth.jwt()->>'plan',
    'free'
  ) in ('pro', 'paid', 'premium');
$$;

drop policy if exists "Users read own mirror metadata" on public.cloud_mirror_snapshots;
create policy "Users read own mirror metadata"
  on public.cloud_mirror_snapshots
  for select
  to authenticated
  using (auth.uid() = user_id and public.mirror_is_pro_jwt());

drop policy if exists "Users upsert own mirror metadata" on public.cloud_mirror_snapshots;
create policy "Users upsert own mirror metadata"
  on public.cloud_mirror_snapshots
  for insert
  to authenticated
  with check (auth.uid() = user_id and public.mirror_is_pro_jwt());

drop policy if exists "Users update own mirror metadata" on public.cloud_mirror_snapshots;
create policy "Users update own mirror metadata"
  on public.cloud_mirror_snapshots
  for update
  to authenticated
  using (auth.uid() = user_id and public.mirror_is_pro_jwt())
  with check (auth.uid() = user_id and public.mirror_is_pro_jwt());

-- Storage RLS: objects live at {user_id}/{profile_id}/{artifact_path}
drop policy if exists "Users read own mirror objects" on storage.objects;
create policy "Users read own mirror objects"
  on storage.objects
  for select
  to authenticated
  using (
    bucket_id = 'baklog-mirror'
    and (storage.foldername(name))[1] = auth.uid()::text
    and public.mirror_is_pro_jwt()
  );

drop policy if exists "Users write own mirror objects" on storage.objects;
create policy "Users write own mirror objects"
  on storage.objects
  for insert
  to authenticated
  with check (
    bucket_id = 'baklog-mirror'
    and (storage.foldername(name))[1] = auth.uid()::text
    and public.mirror_is_pro_jwt()
  );

drop policy if exists "Users update own mirror objects" on storage.objects;
create policy "Users update own mirror objects"
  on storage.objects
  for update
  to authenticated
  using (
    bucket_id = 'baklog-mirror'
    and (storage.foldername(name))[1] = auth.uid()::text
    and public.mirror_is_pro_jwt()
  )
  with check (
    bucket_id = 'baklog-mirror'
    and (storage.foldername(name))[1] = auth.uid()::text
    and public.mirror_is_pro_jwt()
  );

drop policy if exists "Users delete own mirror objects" on storage.objects;
create policy "Users delete own mirror objects"
  on storage.objects
  for delete
  to authenticated
  using (
    bucket_id = 'baklog-mirror'
    and (storage.foldername(name))[1] = auth.uid()::text
    and public.mirror_is_pro_jwt()
  );
