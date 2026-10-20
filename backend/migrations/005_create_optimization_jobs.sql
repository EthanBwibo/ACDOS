-- One row per GA-ALNS run and what triggered it.
create table public.optimization_jobs (
    id uuid primary key default gen_random_uuid(),
    triggered_at timestamptz not null default now(),
    trigger_type text not null
        check (trigger_type in ('scheduled', 'flight_delay', 'standby_activation', 'vehicle_breakdown')),
    status text not null default 'running'
        check (status in ('running', 'completed', 'failed')),
    created_at timestamptz not null default now()
);
