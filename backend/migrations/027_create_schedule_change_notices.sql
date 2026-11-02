-- Dispatcher-to-crew notices of a changed pickup (#53, minimal). As in
-- docs/schema.md (Table 4.1, communication model).
--
-- The job API writes one when a re-plan (#113) changes a crew member's
-- scheduled pickup: a different time or van, or no pickup any more. It
-- writes as postgres, so no client inserts. The crew app shows the pending
-- one and the crew member acknowledges it; nothing else of a notice may
-- change from a client.
--
-- The other communication tables (preset_messages, crew_messages,
-- device_tokens) come with #54 and #55.
create table public.schedule_change_notices (
    id uuid primary key default gen_random_uuid(),
    pickup_request_id uuid not null references public.pickup_requests (id),
    reason text not null
        check (reason in ('flight_delay', 'standby_activation', 'vehicle_breakdown')),
    -- The pickup time crew had been given: the replaced node's ETA.
    previous_pickup_time timestamptz not null,
    -- The new one; null when the re-plan left the pickup unassigned.
    new_pickup_time timestamptz,
    issued_at timestamptz not null default now(),
    -- Set when a push reaches the device (#55); null until then.
    delivered_at timestamptz,
    -- Pending while null.
    acknowledged_at timestamptz,
    created_at timestamptz not null default now()
);

create index schedule_change_notices_pickup_request_id_idx
    on public.schedule_change_notices (pickup_request_id);

alter table public.schedule_change_notices enable row level security;

-- Dispatcher: reads every notice and its status.
create policy schedule_change_notices_dispatcher_select on public.schedule_change_notices
    for select to authenticated
    using ((select private.current_app_role()) = 'dispatcher');

-- Crew: their own notices, read and acknowledge.
create policy schedule_change_notices_crew_select on public.schedule_change_notices
    for select to authenticated
    using (pickup_request_id in (select private.crew_pickup_request_ids()));

create policy schedule_change_notices_crew_acknowledge on public.schedule_change_notices
    for update to authenticated
    using (pickup_request_id in (select private.crew_pickup_request_ids()))
    with check (
        pickup_request_id in (select private.crew_pickup_request_ids())
        and acknowledged_at is not null
    );

-- acknowledged_at is the only column a client may change, and no client
-- inserts or deletes: the policies above match rows, the grants decide
-- columns. Drivers have no policy and see nothing.
revoke insert, update, delete, truncate on public.schedule_change_notices from anon, authenticated;
grant update (acknowledged_at) on public.schedule_change_notices to authenticated;
