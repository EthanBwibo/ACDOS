-- When each route's van leaves the depot and reaches JKIA (#113).
--
-- planned_departure decides when a route has departed: before, it was the
-- first stop's ETA, but a van leaves earlier than that, by the drive from
-- the depot to stop 1, and a van already on its way could be re-planned.
-- planned_arrival decides when the van is free again: it is on the road
-- from planned_departure until planned_arrival plus a grace period (a
-- backend setting), or until its route is completed.
--
-- The job API writes both from the solver's schedule. Routes made before
-- this have neither; they are filled from their stops' ETAs, which keeps
-- the old rule for them: departed at the first stop's ETA, free after the
-- last.
alter table public.routes
    add column planned_departure timestamptz,
    add column planned_arrival timestamptz;

update public.routes r
set planned_departure = coalesce(
        (select min(n.estimated_arrival) from public.route_nodes n
         where n.route_id = r.id and n.superseded_at is null),
        (select min(n.estimated_arrival) from public.route_nodes n where n.route_id = r.id),
        r.created_at
    ),
    planned_arrival = coalesce(
        (select max(n.estimated_arrival) from public.route_nodes n where n.route_id = r.id),
        r.created_at
    );

alter table public.routes
    alter column planned_departure set not null,
    alter column planned_arrival set not null,
    add constraint routes_planned_departure_before_arrival
        check (planned_departure <= planned_arrival);
