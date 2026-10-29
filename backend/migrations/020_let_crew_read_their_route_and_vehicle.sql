-- Crew may read the route and vehicle (plate) of their own live pickup (#52).
--
-- Before, crew had no select on routes or vehicles, so GET /crew/me/pickup
-- could not show which van is coming. Limited to the route and vehicle of
-- the crew member's live route nodes (not superseded), through SECURITY
-- DEFINER helpers in private, as in 012: a direct subquery on route_nodes
-- would recurse through its policies.

-- Routes holding a live node of one of the calling crew member's pickups.
create function private.crew_live_route_ids() returns setof uuid
language sql stable security definer set search_path = ''
as $$
    select n.route_id
    from public.route_nodes n
    where n.superseded_at is null
      and n.pickup_request_id in (select private.crew_pickup_request_ids());
$$;

-- Vehicles of those routes.
create function private.crew_live_vehicle_ids() returns setof uuid
language sql stable security definer set search_path = ''
as $$
    select r.vehicle_id
    from public.routes r
    where r.id in (select private.crew_live_route_ids());
$$;

revoke execute on function
    private.crew_live_route_ids(),
    private.crew_live_vehicle_ids()
from public, anon;

grant execute on function
    private.crew_live_route_ids(),
    private.crew_live_vehicle_ids()
to authenticated;

create policy routes_crew_select on public.routes
    for select to authenticated
    using (id in (select private.crew_live_route_ids()));

create policy vehicles_crew_select on public.vehicles
    for select to authenticated
    using (id in (select private.crew_live_vehicle_ids()));
