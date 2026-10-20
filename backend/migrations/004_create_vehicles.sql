-- A driver reaches their route through the vehicle they are assigned to.
create table public.vehicles (
    id uuid primary key default gen_random_uuid(),
    assigned_driver_id uuid references public.profiles (id),
    plate_number text not null unique,
    capacity int not null check (capacity > 0),
    status text not null default 'available'
        check (status in ('available', 'in_service', 'broken_down')),
    created_at timestamptz not null default now()
);

-- RLS looks vehicles up by driver on every driver query.
create index vehicles_assigned_driver_id_idx on public.vehicles (assigned_driver_id);
