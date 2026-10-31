-- A pickup event moves its pickup request's status (#33), in the same
-- transaction as the event, whatever wrote the event.
--
--   pickup_confirmed    -> picked_up, from assigned or missed (a crew member
--                          marked no-show who turns up is still collected)
--   exception no_show   -> missed, from assigned only
--   vehicle_issue,
--   traffic_delay       -> no change
--
-- Never changes a cancelled pickup, and never moves picked_up back. Drivers
-- have no UPDATE policy on pickup_requests, so the trigger function runs as
-- its owner (SECURITY DEFINER), like the RLS helpers in private.

create function private.apply_pickup_event() returns trigger
language plpgsql security definer set search_path = ''
as $$
declare
    pickup uuid;
begin
    select n.pickup_request_id into pickup
    from public.route_nodes n
    where n.id = new.route_node_id;

    if new.event_type = 'pickup_confirmed' then
        update public.pickup_requests
        set status = 'picked_up'
        where id = pickup and status in ('assigned', 'missed');
    elsif new.exception_type = 'no_show' then
        update public.pickup_requests
        set status = 'missed'
        where id = pickup and status = 'assigned';
    end if;
    return new;
end;
$$;

-- Called only by the trigger, never directly.
revoke execute on function private.apply_pickup_event() from public, anon, authenticated;

create trigger pickup_events_apply_to_pickup
    after insert on public.pickup_events
    for each row execute function private.apply_pickup_event();
