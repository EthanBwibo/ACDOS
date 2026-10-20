-- PostGIS supplies the geography type and ST_Distance / ST_DWithin used for
-- all location queries. Supabase installs extensions into the extensions schema.
create extension if not exists postgis with schema extensions;
