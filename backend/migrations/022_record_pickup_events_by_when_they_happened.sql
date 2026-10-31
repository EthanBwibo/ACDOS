-- Which pickup events a driver may record (#33): judged by whether the stop
-- was theirs when the event happened, not when it syncs.
--
-- An event records something that already happened. A driver can confirm a
-- pickup offline and a re-plan can supersede that stop before the event
-- uploads; rejecting it then would lose a real pickup. So a driver may
-- record an event on a node of a route of their van when either
--   - the node is live and its route is active or completed (a last-stop
--     event can sync after the route is completed), or
--   - the node is superseded, but the event happened before it was:
--     occurred_at (stored in confirmed_at) < superseded_at.
-- Before (011), the policy took any node on any route of the van, whatever
-- its state.
--
-- occurred_at is the device's clock: evidence, not proof. A backdated event
-- could pass the second branch; the dispatcher sees every event.

create function private.driver_may_record(node uuid, occurred timestamptz) returns boolean
language sql stable security definer set search_path = ''
as $$
    select exists (
        select 1
        from public.route_nodes n
        join public.routes r on r.id = n.route_id
        join public.vehicles v on v.id = r.vehicle_id
        where n.id = node
          and v.assigned_driver_id = auth.uid()
          and (
              (n.superseded_at is null and r.status in ('active', 'completed'))
              or occurred < n.superseded_at
          )
    );
$$;

revoke execute on function private.driver_may_record(uuid, timestamptz) from public, anon;
grant execute on function private.driver_may_record(uuid, timestamptz) to authenticated;

alter policy pickup_events_driver_insert on public.pickup_events
    with check (
        driver_id = (select auth.uid())
        and private.driver_may_record(route_node_id, confirmed_at)
    );
