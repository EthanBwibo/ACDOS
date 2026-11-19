-- Vans a job was given but left out (van reuse across waves): a ticked van
-- that already has a route starting after the job's wave keeps that route
-- and stays out of the job, so the job never plans a route that runs into
-- it. The job result lists each one with the later route's times, so the
-- dispatcher sees why the van has no route in this plan.
--
-- The times are copied, not read through route_id: what the dispatcher is
-- told is the route as it was when the job was accepted.
create table public.optimization_job_left_out_vehicles (
    optimization_job_id uuid not null references public.optimization_jobs (id),
    vehicle_id uuid not null references public.vehicles (id),
    reason text not null check (reason in ('later_route')),
    route_id uuid not null references public.routes (id),
    route_departure timestamptz not null,
    route_arrival timestamptz not null,
    created_at timestamptz not null default now(),
    primary key (optimization_job_id, vehicle_id)
);

create index optimization_job_left_out_vehicles_vehicle_id_idx
    on public.optimization_job_left_out_vehicles (vehicle_id);
create index optimization_job_left_out_vehicles_route_id_idx
    on public.optimization_job_left_out_vehicles (route_id);

alter table public.optimization_job_left_out_vehicles enable row level security;

create policy optimization_job_left_out_vehicles_dispatcher_all
    on public.optimization_job_left_out_vehicles
    for all to authenticated
    using ((select private.current_app_role()) = 'dispatcher')
    with check ((select private.current_app_role()) = 'dispatcher');
