-- One completed pickup leg, the unit the Random Forest learns from.
-- Hangs off route_nodes, not routes (Chapter 4 ERD).
create table public.trip_records (
    id uuid primary key default gen_random_uuid(),
    route_node_id uuid not null unique references public.route_nodes (id),
    vehicle_id uuid not null references public.vehicles (id),
    crew_count int not null,
    pickup_timestamp timestamptz not null,
    scheduled_report_time timestamptz not null,
    actual_arrival timestamptz not null,
    actual_duration_sec int not null,
    day_of_week smallint not null,
    route_corridor text not null,
    created_at timestamptz not null default now()
);
