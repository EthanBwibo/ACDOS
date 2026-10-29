-- One row per pickup request an optimisation job was asked to place (#51),
-- with how it came out. Unassigned pickups have no route node, so this is
-- the only place their result is recorded; late ones are listed here too, so
-- every deadline the plan misses is reported explicitly (CLAUDE.md).
-- Re-planning (#113) and the dispatcher's job view (#55) read it.
create table public.optimization_job_pickups (
    id uuid primary key default gen_random_uuid(),
    optimization_job_id uuid not null references public.optimization_jobs (id),
    pickup_request_id uuid not null references public.pickup_requests (id),
    outcome text not null check (outcome in ('on_time', 'late', 'unassigned')),
    -- Seconds the crew member is planned to reach JKIA after report_time.
    -- 0 when on time; null when unassigned (there is no plan to be late by).
    late_sec int check (late_sec >= 0),
    created_at timestamptz not null default now(),
    unique (optimization_job_id, pickup_request_id),
    check ((outcome = 'unassigned') = (late_sec is null))
);

-- The unique constraint covers lookups by job; this one covers by pickup.
create index optimization_job_pickups_pickup_request_id_idx
    on public.optimization_job_pickups (pickup_request_id);

alter table public.optimization_job_pickups enable row level security;

create policy optimization_job_pickups_dispatcher_all on public.optimization_job_pickups
    for all to authenticated
    using ((select private.current_app_role()) = 'dispatcher')
    with check ((select private.current_app_role()) = 'dispatcher');
