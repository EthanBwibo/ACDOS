-- Row level security for profiles and the core tables (docs/schema.md).
-- Dispatcher: read and write operational tables.
-- Driver: read the route of their assigned vehicle, and the pickups and crew
--   on its active routes; insert pickup events.
-- Crew: read their own pickup requests and the route nodes (ETAs) for them.
-- The communication tables get their policies in their own migration (#53).
--
-- Supabase Realtime enforces these policies too, so they are the real access
-- rules for the app, not only a backstop behind FastAPI.

-- Helper functions. Policies must never query a table whose own policies
-- query back (route_nodes <-> pickup_requests would recurse). Every lookup
-- that crosses tables therefore goes through a SECURITY DEFINER function,
-- which runs as its owner and skips RLS. search_path is empty, so every
-- name inside is schema-qualified.

-- The caller's role from profiles, or null when not signed in.
create function public.current_app_role() returns text
language sql stable security definer set search_path = ''
as $$
    select role from public.profiles where id = auth.uid();
$$;

-- The caller's crew_members.id, or null if they are not crew.
create function public.current_crew_member_id() returns uuid
language sql stable security definer set search_path = ''
as $$
    select id from public.crew_members where profile_id = auth.uid();
$$;

-- Pickup requests on active routes of the vehicle the caller drives.
create function public.driver_active_pickup_request_ids() returns setof uuid
language sql stable security definer set search_path = ''
as $$
    select n.pickup_request_id
    from public.route_nodes n
    join public.routes r on r.id = n.route_id
    join public.vehicles v on v.id = r.vehicle_id
    where r.status = 'active'
      and v.assigned_driver_id = auth.uid();
$$;

-- Crew members behind those pickup requests.
create function public.driver_active_crew_member_ids() returns setof uuid
language sql stable security definer set search_path = ''
as $$
    select p.crew_member_id
    from public.pickup_requests p
    where p.id in (select public.driver_active_pickup_request_ids());
$$;

-- Pickup requests that belong to the calling crew member.
create function public.crew_pickup_request_ids() returns setof uuid
language sql stable security definer set search_path = ''
as $$
    select p.id
    from public.pickup_requests p
    join public.crew_members c on c.id = p.crew_member_id
    where c.profile_id = auth.uid();
$$;

alter table public.profiles enable row level security;
alter table public.crew_members enable row level security;
alter table public.vehicles enable row level security;
alter table public.optimization_jobs enable row level security;
alter table public.pickup_requests enable row level security;
alter table public.routes enable row level security;
alter table public.route_nodes enable row level security;
alter table public.pickup_events enable row level security;
alter table public.trip_records enable row level security;

-- Policies wrap auth.uid() and the helpers in (select ...) so Postgres
-- evaluates them once per query instead of once per row.

-- profiles: everyone reads their own row; dispatchers read all (driver names).
create policy profiles_select_own on public.profiles
    for select to authenticated
    using (id = (select auth.uid()));

create policy profiles_dispatcher_select on public.profiles
    for select to authenticated
    using ((select public.current_app_role()) = 'dispatcher');

-- Dispatcher: full access to the operational tables.
create policy crew_members_dispatcher_all on public.crew_members
    for all to authenticated
    using ((select public.current_app_role()) = 'dispatcher')
    with check ((select public.current_app_role()) = 'dispatcher');

create policy vehicles_dispatcher_all on public.vehicles
    for all to authenticated
    using ((select public.current_app_role()) = 'dispatcher')
    with check ((select public.current_app_role()) = 'dispatcher');

create policy optimization_jobs_dispatcher_all on public.optimization_jobs
    for all to authenticated
    using ((select public.current_app_role()) = 'dispatcher')
    with check ((select public.current_app_role()) = 'dispatcher');

create policy pickup_requests_dispatcher_all on public.pickup_requests
    for all to authenticated
    using ((select public.current_app_role()) = 'dispatcher')
    with check ((select public.current_app_role()) = 'dispatcher');

create policy routes_dispatcher_all on public.routes
    for all to authenticated
    using ((select public.current_app_role()) = 'dispatcher')
    with check ((select public.current_app_role()) = 'dispatcher');

create policy route_nodes_dispatcher_all on public.route_nodes
    for all to authenticated
    using ((select public.current_app_role()) = 'dispatcher')
    with check ((select public.current_app_role()) = 'dispatcher');

create policy pickup_events_dispatcher_all on public.pickup_events
    for all to authenticated
    using ((select public.current_app_role()) = 'dispatcher')
    with check ((select public.current_app_role()) = 'dispatcher');

create policy trip_records_dispatcher_all on public.trip_records
    for all to authenticated
    using ((select public.current_app_role()) = 'dispatcher')
    with check ((select public.current_app_role()) = 'dispatcher');

-- Driver: vehicle -> routes -> route nodes, only for their assigned vehicle.
create policy vehicles_driver_select on public.vehicles
    for select to authenticated
    using (assigned_driver_id = (select auth.uid()));

create policy routes_driver_select on public.routes
    for select to authenticated
    using (
        vehicle_id in (
            select id from public.vehicles
            where assigned_driver_id = (select auth.uid())
        )
    );

create policy route_nodes_driver_select on public.route_nodes
    for select to authenticated
    using (
        route_id in (
            select r.id from public.routes r
            join public.vehicles v on v.id = r.vehicle_id
            where v.assigned_driver_id = (select auth.uid())
        )
    );

-- Driver: who to pick up and where, only on active routes of their vehicle.
create policy pickup_requests_driver_select on public.pickup_requests
    for select to authenticated
    using (id in (select public.driver_active_pickup_request_ids()));

create policy crew_members_driver_select on public.crew_members
    for select to authenticated
    using (id in (select public.driver_active_crew_member_ids()));

-- A driver can only record events as themselves, on a stop of their own route.
create policy pickup_events_driver_insert on public.pickup_events
    for insert to authenticated
    with check (
        driver_id = (select auth.uid())
        and route_node_id in (
            select n.id from public.route_nodes n
            join public.routes r on r.id = n.route_id
            join public.vehicles v on v.id = r.vehicle_id
            where v.assigned_driver_id = (select auth.uid())
        )
    );

-- Crew: their own pickup requests, and the route nodes (ETAs) for them.
create policy pickup_requests_crew_select on public.pickup_requests
    for select to authenticated
    using (crew_member_id = (select public.current_crew_member_id()));

create policy route_nodes_crew_select on public.route_nodes
    for select to authenticated
    using (pickup_request_id in (select public.crew_pickup_request_ids()));
