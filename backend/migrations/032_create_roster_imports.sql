-- One row per roster import the dispatcher commits (#229), keyed by the
-- app's Idempotency-Key header: a retry on a bad connection finds the import
-- it already made and gets its result back, instead of importing the file
-- twice. A dry run writes nothing, so it has no row.

create table public.roster_imports (
    id uuid primary key default gen_random_uuid(),
    idempotency_key text not null unique,
    -- SHA-256 of the uploaded file: the same key with a different file is
    -- refused, not answered with the first file's result.
    file_hash text not null,
    imported_by uuid not null references public.profiles (id),
    -- The response sent the first time (counts and rejected rows), sent
    -- again unchanged on a retry.
    result jsonb not null,
    created_at timestamptz not null default now()
);

create index roster_imports_imported_by_idx on public.roster_imports (imported_by);

alter table public.roster_imports enable row level security;

-- Only the dispatcher imports a roster, and records the import as themselves.
create policy roster_imports_dispatcher_insert on public.roster_imports
    for insert to authenticated
    with check (
        (select private.current_app_role()) = 'dispatcher'
        and imported_by = (select auth.uid())
    );

create policy roster_imports_dispatcher_select on public.roster_imports
    for select to authenticated
    using ((select private.current_app_role()) = 'dispatcher');

-- An import is a record of what happened: never edited or deleted by a client.
revoke insert, update, delete, truncate on public.roster_imports from anon, authenticated;
grant insert on public.roster_imports to authenticated;
