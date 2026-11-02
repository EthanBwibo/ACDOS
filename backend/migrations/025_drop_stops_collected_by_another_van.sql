-- A pickup collected by a van it was re-planned away from comes off the
-- other van's route at once (#113).
--
-- #33 accepts a confirmation on a superseded node when it happened before
-- the re-plan (a driver confirmed offline). The pickup is then picked_up
-- (023), but it still has a live node on the route it was re-planned to,
-- and that van's driver would be sent to a pickup already collected.
--
-- So when a pickup_confirmed is recorded on a superseded node, the pickup's
-- live node is superseded too, unless that node has an event of its own (its
-- van has been there; both stay as recorded, for the dispatcher). A route
-- left with no live node is marked superseded: nothing is left to drive.
-- Drivers do not see superseded nodes (021), and a later confirmation from
-- the other van is refused by 022, since it happened after superseded_at.

create function private.drop_stop_collected_elsewhere() returns trigger
language plpgsql security definer set search_path = ''
as $$
declare
    pickup uuid;
    dropped_route uuid;
begin
    if new.event_type <> 'pickup_confirmed' then
        return new;
    end if;

    select n.pickup_request_id into pickup
    from public.route_nodes n
    where n.id = new.route_node_id and n.superseded_at is not null;
    if pickup is null then
        return new;  -- confirmed on its live node: the usual case
    end if;

    update public.route_nodes n
    set superseded_at = now()
    where n.pickup_request_id = pickup
      and n.superseded_at is null
      and not exists (select 1 from public.pickup_events e where e.route_node_id = n.id)
    returning n.route_id into dropped_route;

    update public.routes r
    set status = 'superseded'
    where r.id = dropped_route
      and r.status = 'active'
      and not exists (
          select 1 from public.route_nodes n
          where n.route_id = r.id and n.superseded_at is null
      );
    return new;
end;
$$;

-- Called only by the trigger, never directly.
revoke execute on function private.drop_stop_collected_elsewhere() from public, anon, authenticated;

create trigger pickup_events_drop_stop_collected_elsewhere
    after insert on public.pickup_events
    for each row execute function private.drop_stop_collected_elsewhere();
