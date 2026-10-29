-- Drivers read only live route nodes (#52).
--
-- 018 gave the crew policy this filter; route_nodes_driver_select lacked it,
-- so a driver could see the stops a later job replaced.
alter policy route_nodes_driver_select on public.route_nodes
    using (
        superseded_at is null
        and route_id in (
            select r.id from public.routes r
            join public.vehicles v on v.id = r.vehicle_id
            where v.assigned_driver_id = (select auth.uid())
        )
    );
