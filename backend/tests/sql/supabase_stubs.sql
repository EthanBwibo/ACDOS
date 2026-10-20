-- Minimal stand-ins for what Supabase provides, so CI can apply
-- backend/migrations to a plain PostGIS container. Never applied to Supabase.

create schema if not exists auth;
create schema if not exists extensions;

create table auth.users (id uuid primary key);

create role authenticated nologin;
create role anon nologin;

grant usage on schema public, auth, extensions to authenticated, anon;
alter default privileges in schema public
    grant select, insert, update, delete on tables to authenticated, anon;

-- Supabase's auth.uid() reads the subject of the caller's JWT. Here it reads
-- a session setting, which the RLS test sets to impersonate each user.
create function auth.uid() returns uuid
language sql stable
as $$
    select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid;
$$;

grant execute on function auth.uid() to authenticated, anon;
