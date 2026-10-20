-- One pickup per crew member per duty. report_time is the hard deadline at JKIA.
create table public.pickup_requests (
    id uuid primary key default gen_random_uuid(),
    crew_member_id uuid not null references public.crew_members (id),
    pickup_location geography(Point, 4326) not null,
    report_time timestamptz not null,
    request_type text not null check (request_type in ('rostered', 'standby')),
    status text not null default 'pending'
        check (status in ('pending', 'assigned', 'picked_up', 'missed', 'cancelled')),
    created_at timestamptz not null default now()
);

-- Spatial index so ST_DWithin / ST_Distance on pickup locations can use it.
create index pickup_requests_pickup_location_gist on public.pickup_requests
    using gist (pickup_location);

-- RLS filters crew pickups by crew member.
create index pickup_requests_crew_member_id_idx on public.pickup_requests (crew_member_id);
