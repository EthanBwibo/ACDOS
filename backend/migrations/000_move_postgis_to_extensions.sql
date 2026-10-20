-- PostGIS was first enabled from the Supabase dashboard, which put it in the
-- public schema. That exposes public.spatial_ref_sys through the Supabase API
-- with RLS off (security advisor: critical). Supabase recommends the
-- extensions schema, which the API does not expose; 001 creates it there.
--
-- PostGIS cannot be moved with ALTER EXTENSION ... SET SCHEMA, so it is
-- dropped here and recreated by 001. That is only safe before any table uses
-- PostGIS, which is why this runs first. No CASCADE: if anything did depend
-- on PostGIS, the drop fails instead of silently removing it.
do $$
begin
    if exists (
        select 1
        from pg_extension e
        join pg_namespace n on n.oid = e.extnamespace
        where e.extname = 'postgis' and n.nspname <> 'extensions'
    ) then
        drop extension postgis;
    end if;
end $$;
