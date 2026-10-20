-- One stop on a route. Each pickup request is placed on at most one route
-- node, and no two stops on a route share a position.
create table public.route_nodes (
    id uuid primary key default gen_random_uuid(),
    route_id uuid not null references public.routes (id),
    pickup_request_id uuid not null unique references public.pickup_requests (id),
    seq_order int not null,
    estimated_arrival timestamptz not null,
    created_at timestamptz not null default now(),
    unique (route_id, seq_order)
);
