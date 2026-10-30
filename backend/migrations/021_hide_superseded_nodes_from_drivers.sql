-- Drivers read only live route nodes (#52), and only the pickups and crew
-- behind live nodes.
--
-- 018 gave the crew policy this filter; route_nodes_driver_select lacked it,
-- so a driver could see the stops a later job replaced. The helper behind
-- the driver's pickup_requests and crew_members policies (011, moved to
-- private by 012) had the same gap: it followed any node on an active route,
-- so a superseded node there would show the driver the replaced crew
-- member's pickup and name.
alter policy route_nodes_driver_select on public.route_nodes
    using (
        superseded_at is null
        and route_id in (
            select r.id from public.routes r
            join public.vehicles v on v.id = r.vehicle_id
            where v.assigned_driver_id = (select auth.uid())
        )
    );

-- Same body as in 012, plus the superseded_at filter. CREATE OR REPLACE
-- keeps the function's owner and its grants (authenticated only).
create or replace function private.driver_active_pickup_request_ids() returns setof uuid
language sql stable security definer set search_path = ''
as $$
    select n.pickup_request_id
    from public.route_nodes n
    join public.routes r on r.id = n.route_id
    join public.vehicles v on v.id = r.vehicle_id
    where r.status = 'active'
      and n.superseded_at is null
      and v.assigned_driver_id = auth.uid();
$$;
