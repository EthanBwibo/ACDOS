-- Let a later optimisation job re-plan a pickup (#51) while the database
-- still allows only one live assignment per pickup.
--
-- Before: route_nodes.pickup_request_id was unique, so a pickup could be on
-- one route node ever, and the second job over it failed on insert.
-- After: a node is superseded (superseded_at set) when a later job re-plans
-- its pickup, and the uniqueness holds only among nodes not superseded.
-- The API sets superseded_at and marks the old route superseded in the same
-- transaction that writes the new route.
alter table public.route_nodes
    add column superseded_at timestamptz;

-- Nodes already on superseded routes count as superseded from when the
-- route was made: there is no record of when it was replaced.
update public.route_nodes n
set superseded_at = r.created_at
from public.routes r
where r.id = n.route_id
  and r.status = 'superseded';

alter table public.route_nodes
    drop constraint route_nodes_pickup_request_id_key;

create unique index route_nodes_live_pickup_request_id_key
    on public.route_nodes (pickup_request_id)
    where superseded_at is null;

-- The partial index only serves queries that filter on superseded_at, so
-- the foreign key keeps a plain index of its own.
create index route_nodes_pickup_request_id_idx on public.route_nodes (pickup_request_id);

-- Crew see the ETA of their current plan only, not the ones replaced.
alter policy route_nodes_crew_select on public.route_nodes
    using (
        superseded_at is null
        and pickup_request_id in (select private.crew_pickup_request_ids())
    );
