-- BAKLOG Pro entitlement helper (run once in the Supabase SQL editor).
-- Used by landing/api/polar-webhook.js to map a Polar buyer's email to their
-- Supabase user id, after which the webhook writes app_metadata.plan via the
-- GoTrue admin API. The auth schema is not exposed over PostgREST, so a
-- SECURITY DEFINER function is the supported way to read it with service_role.

create or replace function public.get_user_id_by_email(input_email text)
returns uuid
language sql
security definer
set search_path = ''
as $$
  select id
  from auth.users
  where lower(email) = lower(input_email)
  limit 1;
$$;

-- Only the service_role (used by the Vercel webhook) may call this. Revoke the
-- default execute grant from anon/authenticated so end users can't enumerate ids.
revoke execute on function public.get_user_id_by_email(text) from public, anon, authenticated;
grant execute on function public.get_user_id_by_email(text) to service_role;
