-- Checks the RLS policies (011, helpers moved to private by 012), the
-- pickup_events confirmation index, one live route node per pickup (018),
-- pickup zones (019), crew reading their own route and van (020) and drivers
-- reading only live stops (021), by impersonating each role.
-- Seed data is inserted as the superuser, which bypasses RLS.
-- Any failed assert stops psql (ON_ERROR_STOP) and fails CI.

-- Users: dispatcher D, drivers A and B, crew member C (with an account).
insert into auth.users (id) values
    ('00000000-0000-0000-0000-00000000000d'),
    ('00000000-0000-0000-0000-00000000000a'),
    ('00000000-0000-0000-0000-00000000000b'),
    ('00000000-0000-0000-0000-00000000000c');

insert into public.profiles (id, role, full_name) values
    ('00000000-0000-0000-0000-00000000000d', 'dispatcher', 'Dispatcher D'),
    ('00000000-0000-0000-0000-00000000000a', 'driver', 'Driver A'),
    ('00000000-0000-0000-0000-00000000000b', 'driver', 'Driver B'),
    ('00000000-0000-0000-0000-00000000000c', 'crew', 'Crew C');

-- Crew C has an account; crew E and F do not (profile_id null).
insert into public.crew_members (id, profile_id, name, role, home_location) values
    ('10000000-0000-0000-0000-00000000000c', '00000000-0000-0000-0000-00000000000c',
     'Crew C', 'cabin_crew', 'SRID=4326;POINT(36.8120 -1.2675)'),
    ('10000000-0000-0000-0000-00000000000e', null,
     'Crew E', 'pilot', 'SRID=4326;POINT(36.7778 -1.2789)'),
    ('10000000-0000-0000-0000-00000000000f', null,
     'Crew F', 'cabin_crew', 'SRID=4326;POINT(36.8219 -1.2921)');

insert into public.vehicles (id, assigned_driver_id, plate_number, capacity) values
    ('20000000-0000-0000-0000-00000000000a', '00000000-0000-0000-0000-00000000000a', 'KDA 001A', 14),
    ('20000000-0000-0000-0000-00000000000b', '00000000-0000-0000-0000-00000000000b', 'KDB 002B', 14);

insert into public.optimization_jobs (id, trigger_type, status) values
    ('30000000-0000-0000-0000-000000000000', 'scheduled', 'completed'),
    ('30000000-0000-0000-0000-000000000001', 'flight_delay', 'completed');

insert into public.pickup_requests (id, crew_member_id, pickup_location, report_time, request_type) values
    ('40000000-0000-0000-0000-00000000000c', '10000000-0000-0000-0000-00000000000c',
     'SRID=4326;POINT(36.8120 -1.2675)', '2026-11-01T04:10:00Z', 'rostered'),
    ('40000000-0000-0000-0000-00000000000e', '10000000-0000-0000-0000-00000000000e',
     'SRID=4326;POINT(36.7778 -1.2789)', '2026-11-01T04:40:00Z', 'standby'),
    ('40000000-0000-0000-0000-00000000000f', '10000000-0000-0000-0000-00000000000f',
     'SRID=4326;POINT(36.8219 -1.2921)', '2026-11-01T05:00:00Z', 'rostered');

-- Active routes: vehicle A picks up crew C, vehicle B picks up crew E.
-- Vehicle A also has an older, superseded route that held crew F.
insert into public.routes (id, vehicle_id, optimization_job_id, total_distance_km, status) values
    ('50000000-0000-0000-0000-00000000000a', '20000000-0000-0000-0000-00000000000a',
     '30000000-0000-0000-0000-000000000001', 14.1, 'active'),
    ('50000000-0000-0000-0000-00000000000b', '20000000-0000-0000-0000-00000000000b',
     '30000000-0000-0000-0000-000000000001', 17.3, 'active'),
    ('50000000-0000-0000-0000-0000000000a0', '20000000-0000-0000-0000-00000000000a',
     '30000000-0000-0000-0000-000000000000', 9.8, 'superseded');

insert into public.route_nodes (id, route_id, pickup_request_id, seq_order, estimated_arrival) values
    ('60000000-0000-0000-0000-00000000000a', '50000000-0000-0000-0000-00000000000a',
     '40000000-0000-0000-0000-00000000000c', 1, '2026-11-01T03:40:00Z'),
    ('60000000-0000-0000-0000-00000000000b', '50000000-0000-0000-0000-00000000000b',
     '40000000-0000-0000-0000-00000000000e', 1, '2026-11-01T04:05:00Z'),
    ('60000000-0000-0000-0000-0000000000a0', '50000000-0000-0000-0000-0000000000a0',
     '40000000-0000-0000-0000-00000000000f', 1, '2026-11-01T04:20:00Z');

-- The superseded route held crew C too, at an earlier ETA: an old plan for C,
-- replaced by the active route above (018). Its nodes are superseded.
insert into public.route_nodes
    (id, route_id, pickup_request_id, seq_order, estimated_arrival, superseded_at) values
    ('60000000-0000-0000-0000-0000000000c0', '50000000-0000-0000-0000-0000000000a0',
     '40000000-0000-0000-0000-00000000000c', 2, '2026-11-01T03:30:00Z', '2026-10-31T20:00:00Z');
update public.route_nodes set superseded_at = '2026-10-31T20:00:00Z'
where id = '60000000-0000-0000-0000-0000000000a0';

-- Only one live node per pickup: a second one for crew C is refused.
do $$
begin
    insert into public.route_nodes (route_id, pickup_request_id, seq_order, estimated_arrival)
    values ('50000000-0000-0000-0000-00000000000b', '40000000-0000-0000-0000-00000000000c', 2,
            '2026-11-01T04:15:00Z');
    raise exception 'a pickup got two live route nodes';
exception when unique_violation then
    null; -- expected: route_nodes_live_pickup_request_id_key
end $$;

-- How crew E came out of the latest job (017).
insert into public.optimization_job_pickups (optimization_job_id, pickup_request_id, outcome, late_sec)
values ('30000000-0000-0000-0000-000000000001', '40000000-0000-0000-0000-00000000000e', 'late', 120);

set role authenticated;

-- Driver A ---------------------------------------------------------------
set request.jwt.claim.sub = '00000000-0000-0000-0000-00000000000a';

-- Sees their own vehicle and its routes (active and superseded), not B's,
-- and only the live stops (021): the superseded route's two stops are hidden.
do $$
begin
    assert (select count(*) from public.vehicles) = 1, 'driver A should see 1 vehicle';
    assert (select count(*) from public.routes) = 2, 'driver A should see the 2 routes of vehicle A';
    assert (select count(*) from public.route_nodes) = 1, 'driver A should see the 1 live stop of vehicle A';
    assert (select id from public.route_nodes) = '60000000-0000-0000-0000-00000000000a',
        'driver A should see the live stop for crew C, not the superseded ones';
    assert (select count(*) from public.optimization_job_pickups) = 0,
        'driver A should see no job outcomes';
    assert (select count(*) from public.trip_records) = 0, 'driver A should see no trip records';
end $$;

-- Sees the crew and pickups on their active route only: C, not E (driver B's
-- crew) and not F (superseded route).
do $$
begin
    assert (select count(*) from public.pickup_requests) = 1, 'driver A should see 1 pickup request';
    assert (select id from public.pickup_requests) = '40000000-0000-0000-0000-00000000000c',
        'driver A should see the pickup of crew C';
    assert (select count(*) from public.crew_members) = 1, 'driver A should see 1 crew member';
    assert (select id from public.crew_members) = '10000000-0000-0000-0000-00000000000c',
        'driver A should see crew C only, not the crew of driver B';
end $$;

-- An exception, then a confirmation, on the same stop: both allowed.
insert into public.pickup_events (route_node_id, driver_id, event_type, exception_type, confirmed_at, idempotency_key)
values ('60000000-0000-0000-0000-00000000000a', '00000000-0000-0000-0000-00000000000a',
        'exception', 'traffic_delay', '2026-11-01T03:38:00Z', 'device-a-1');
insert into public.pickup_events (route_node_id, driver_id, event_type, confirmed_at, idempotency_key)
values ('60000000-0000-0000-0000-00000000000a', '00000000-0000-0000-0000-00000000000a',
        'pickup_confirmed', '2026-11-01T03:41:00Z', 'device-a-2');

-- A second confirmation on the same stop is rejected.
do $$
begin
    insert into public.pickup_events (route_node_id, driver_id, event_type, confirmed_at, idempotency_key)
    values ('60000000-0000-0000-0000-00000000000a', '00000000-0000-0000-0000-00000000000a',
            'pickup_confirmed', '2026-11-01T03:45:00Z', 'device-a-3');
    raise exception 'a stop was confirmed twice';
exception when unique_violation then
    null; -- expected: pickup_events_one_confirmation_per_node
end $$;

-- No events on driver B's route.
do $$
begin
    insert into public.pickup_events (route_node_id, driver_id, event_type, confirmed_at, idempotency_key)
    values ('60000000-0000-0000-0000-00000000000b', '00000000-0000-0000-0000-00000000000a',
            'pickup_confirmed', '2026-11-01T04:06:00Z', 'device-a-4');
    raise exception 'driver A inserted an event on the route of driver B';
exception when insufficient_privilege then
    null; -- expected: blocked by RLS
end $$;

-- No events while claiming to be driver B.
do $$
begin
    insert into public.pickup_events (route_node_id, driver_id, event_type, exception_type, confirmed_at, idempotency_key)
    values ('60000000-0000-0000-0000-00000000000a', '00000000-0000-0000-0000-00000000000b',
            'exception', 'no_show', '2026-11-01T03:42:00Z', 'device-a-5');
    raise exception 'driver A inserted an event as driver B';
exception when insufficient_privilege then
    null; -- expected: blocked by RLS
end $$;

-- Crew C ------------------------------------------------------------------
set request.jwt.claim.sub = '00000000-0000-0000-0000-00000000000c';

-- Sees their own pickup and its live ETA; not the ETA it replaced (018), nor
-- the ETA of crew E or F.
do $$
begin
    assert (select count(*) from public.pickup_requests) = 1, 'crew C should see 1 pickup request';
    assert (select crew_member_id from public.pickup_requests)
        = '10000000-0000-0000-0000-00000000000c', 'crew C should see their own request';
    assert (select count(*) from public.route_nodes) = 1, 'crew C should see 1 route node';
    assert (select estimated_arrival from public.route_nodes) = '2026-11-01T03:40:00Z',
        'crew C should see only their own ETA';
    -- The route and van of their live stop (020): which van is coming. Not
    -- the superseded route, nor driver B's.
    assert (select count(*) from public.routes) = 1, 'crew C should see 1 route';
    assert (select id from public.routes) = '50000000-0000-0000-0000-00000000000a',
        'crew C should see only the route of their live stop';
    assert (select count(*) from public.vehicles) = 1, 'crew C should see 1 vehicle';
    assert (select plate_number from public.vehicles) = 'KDA 001A',
        'crew C should see only the van coming for them';
    assert (select count(*) from public.profiles) = 1, 'crew C should see only their own profile';
    assert (select count(*) from public.optimization_job_pickups) = 0,
        'crew C should see no job outcomes';
end $$;

-- Dispatcher D ------------------------------------------------------------
set request.jwt.claim.sub = '00000000-0000-0000-0000-00000000000d';
do $$
begin
    assert (select count(*) from public.routes) = 3, 'dispatcher should see 3 routes';
    assert (select count(*) from public.route_nodes) = 4, 'dispatcher should see 4 route nodes';
    assert (select count(*) from public.optimization_job_pickups) = 1,
        'dispatcher should see the job outcome';
    assert (select count(*) from public.pickup_requests) = 3, 'dispatcher should see 3 requests';
    assert (select count(*) from public.crew_members) = 3, 'dispatcher should see 3 crew members';
    assert (select count(*) from public.pickup_events) = 2, 'dispatcher should see 2 events';
    assert (select count(*) from public.profiles) = 4, 'dispatcher should see 4 profiles';
end $$;
insert into public.vehicles (plate_number, capacity) values ('KDC 003C', 7);

-- Not signed in -----------------------------------------------------------
reset request.jwt.claim.sub;
do $$
begin
    assert (select count(*) from public.vehicles) = 0, 'no user should see no vehicles';
    assert (select count(*) from public.pickup_requests) = 0, 'no user should see no requests';
    assert (select count(*) from public.route_nodes) = 0, 'no user should see no route nodes';
end $$;

reset role;

-- RLS helper functions (012) ----------------------------------------------
-- None left in public, where the API would expose them as RPC endpoints.
do $$
begin
    assert not exists (
        select 1 from pg_proc
        where pronamespace = 'public'::regnamespace
          and proname in ('current_app_role', 'current_crew_member_id',
                          'driver_active_pickup_request_ids',
                          'driver_active_crew_member_ids', 'crew_pickup_request_ids')
    ), 'an RLS helper function is still in the public schema';
end $$;

-- Not callable without signing in.
set role anon;
do $$
begin
    perform private.current_app_role();
    raise exception 'anon was able to call private.current_app_role()';
exception when insufficient_privilege then
    null; -- expected: no access to the private schema
end $$;
reset role;

-- The crew helpers added in 020: authenticated only, like 012's.
do $$
begin
    assert has_function_privilege('authenticated', 'private.crew_live_route_ids()', 'execute')
        and has_function_privilege('authenticated', 'private.crew_live_vehicle_ids()', 'execute'),
        'authenticated must be able to call the 020 helpers';
    assert not has_function_privilege('anon', 'private.crew_live_route_ids()', 'execute')
        and not has_function_privilege('anon', 'private.crew_live_vehicle_ids()', 'execute'),
        'anon must not be able to call the 020 helpers';
end $$;

-- Pickup zones (019) ------------------------------------------------------
-- Reference data: every signed-in user reads all 28; nobody writes; anon
-- reads nothing.
set role authenticated;
set request.jwt.claim.sub = '00000000-0000-0000-0000-00000000000c';
do $$
begin
    assert (select count(*) from public.pickup_zones) = 28, 'crew C should see the 28 zones';
end $$;
do $$
begin
    insert into public.pickup_zones (label, location)
    values ('Nowhere', 'SRID=4326;POINT(36.8 -1.3)');
    raise exception 'a signed-in user inserted a pickup zone';
exception when insufficient_privilege then
    null; -- expected: no write grant
end $$;
reset request.jwt.claim.sub;
reset role;
set role anon;
do $$
begin
    assert (select count(*) from public.pickup_zones) = 0, 'anon should see no zones';
end $$;
reset role;

-- Travel time observations (014) -------------------------------------------
-- Written only by the Edge Function (service role, which bypasses RLS);
-- dispatchers read, nobody else does, and no client writes.
insert into public.travel_time_observations
    (logged_at_utc, logged_at_eat, day_of_week, hour_eat, minute_eat, zone,
     origin_lat, origin_lon, element_status, distance_m, duration_sec,
     duration_in_traffic_sec, run_id)
values ('2026-10-20T03:42:29Z', '2026-10-20T06:42:29', 'Tuesday', 6, 42,
        'South B, Nairobi', -1.310341, 36.833737, 'OK', 13268, 1001, 849, 'ci');

set role authenticated;
set request.jwt.claim.sub = '00000000-0000-0000-0000-00000000000d';
do $$
begin
    assert (select count(*) from public.travel_time_observations) = 1,
        'dispatcher should see the travel time observation';
end $$;
do $$
begin
    insert into public.travel_time_observations
        (logged_at_utc, logged_at_eat, day_of_week, hour_eat, minute_eat, zone,
         origin_lat, origin_lon, element_status, run_id)
    values (now(), now(), 'Tuesday', 6, 42, 'South C, Nairobi', -1.32, 36.83, 'OK', 'ci-2');
    raise exception 'dispatcher inserted a travel time observation';
exception when insufficient_privilege then
    null; -- expected: insert revoked from authenticated
end $$;

set request.jwt.claim.sub = '00000000-0000-0000-0000-00000000000a';
do $$
begin
    assert (select count(*) from public.travel_time_observations) = 0,
        'driver A should see no travel time observations';
end $$;
reset request.jwt.claim.sub;
reset role;

\echo 'RLS smoke test passed'
