-- supabase-only: public.rls_auto_enable() is Supabase's, not created by any
-- migration here, so CI's plain Postgres doesn't have it.
--
-- rls_auto_enable() is the function behind Supabase's ensure_rls event
-- trigger, which turns RLS on for every new table in public. It is SECURITY
-- DEFINER, owned by postgres, and anon and authenticated could call it
-- (security advisor: function executable by anon/authenticated). Nothing
-- should call it directly. Event triggers don't check EXECUTE when they fire,
-- so ensure_rls keeps working: after applying this, a new table in public
-- still had RLS on. postgres and service_role keep EXECUTE.

revoke execute on function public.rls_auto_enable() from public, anon, authenticated;
