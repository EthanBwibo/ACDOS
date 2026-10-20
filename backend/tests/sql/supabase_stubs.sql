-- Minimal stand-ins for what Supabase provides, so CI can apply
-- backend/migrations to a clean database in a PostGIS container.
-- Never applied to Supabase.

create schema if not exists auth;
create schema if not exists extensions;

-- Supabase's default search path. Migrations name PostGIS types (geography)
-- without a schema, which works because extensions is on this path.
-- Takes effect for the later psql sessions that apply each migration.
alter database acdos_ci set search_path = "$user", public, extensions;

-- PostGIS as the ACDOS project had it before #62: enabled from the
-- dashboard into public. 000 then has to move it, so CI tests that move.
create extension postgis;

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
