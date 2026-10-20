-- One vehicle's route produced by an optimisation job. A later job marks
-- older routes superseded instead of deleting them.
create table public.routes (
    id uuid primary key default gen_random_uuid(),
    vehicle_id uuid not null references public.vehicles (id),
    optimization_job_id uuid not null references public.optimization_jobs (id),
    total_distance_km numeric not null,
    status text not null default 'active'
        check (status in ('active', 'completed', 'superseded')),
    created_at timestamptz not null default now()
);

create index routes_vehicle_id_idx on public.routes (vehicle_id);
create index routes_optimization_job_id_idx on public.routes (optimization_job_id);
