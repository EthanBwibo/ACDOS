-- The driver's confirmation (or exception) for a route node, written on the
-- device first and synced later. synced_at stays null until synchronised.
create table public.pickup_events (
    id uuid primary key default gen_random_uuid(),
    route_node_id uuid not null references public.route_nodes (id),
    driver_id uuid not null references public.profiles (id),
    event_type text not null check (event_type in ('pickup_confirmed', 'exception')),
    exception_type text check (exception_type in ('no_show', 'vehicle_issue', 'traffic_delay')),
    confirmed_at timestamptz not null,
    synced_at timestamptz,
    -- Generated on the device, so a retried upload cannot create a second event.
    idempotency_key text not null unique,
    created_at timestamptz not null default now()
);

-- A stop can collect several exceptions (e.g. traffic delay, then no show)
-- but can be confirmed at most once.
create unique index pickup_events_one_confirmation_per_node
    on public.pickup_events (route_node_id)
    where event_type = 'pickup_confirmed';
