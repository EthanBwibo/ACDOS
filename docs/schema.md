# Database schema (Chapter 4, Table 4.1)

Source of truth for all Supabase migrations. Copied from the Chapter 4 database schema
(Section 4.3.5). If this file and the code models disagree, this file wins.

Every table has a UUID primary key and a UTC `created_at`. Locations are
`GEOGRAPHY(Point, 4326)`. All distance queries use PostGIS `ST_Distance` on geography columns.

## Core model (ERD Figure: core)

| Table | Columns | Keys and constraints |
|---|---|---|
| profiles | id UUID; role TEXT; full_name TEXT; created_at TIMESTAMPTZ | PK id, FK to auth.users; role in (dispatcher, driver, crew) |
| crew_members | id UUID; profile_id UUID; name TEXT; role TEXT; home_location GEOGRAPHY(Point, 4326); created_at TIMESTAMPTZ | PK id; FK profile_id to profiles, nullable and unique |
| vehicles | id UUID; assigned_driver_id UUID; plate_number TEXT; capacity INT; status TEXT; created_at TIMESTAMPTZ | PK id; FK assigned_driver_id to profiles; plate_number unique; capacity above 0; status in (available, in_service, broken_down) |
| optimization_jobs | id UUID; triggered_at TIMESTAMPTZ; trigger_type TEXT; status TEXT; idempotency_key TEXT; request_hash TEXT; error TEXT; finished_at TIMESTAMPTZ; created_at TIMESTAMPTZ | PK id; trigger_type in (scheduled, flight_delay, standby_activation, vehicle_breakdown); status in (queued, running, completed, failed), default queued; idempotency_key unique, null for jobs not made through the API; error and finished_at null until the job fails or completes |
| optimization_job_pickups | id UUID; optimization_job_id UUID; pickup_request_id UUID; outcome TEXT; late_sec INT; created_at TIMESTAMPTZ | PK id; FK optimization_job_id, pickup_request_id; optimization_job_id and pickup_request_id unique together; outcome in (on_time, late, unassigned); late_sec at least 0, null exactly when unassigned |
| pickup_requests | id UUID; crew_member_id UUID; pickup_location GEOGRAPHY(Point, 4326); report_time TIMESTAMPTZ; request_type TEXT; status TEXT; created_at TIMESTAMPTZ | PK id; FK crew_member_id; request_type in (rostered, standby); status in (pending, assigned, picked_up, missed, cancelled); spatial index on pickup_location |
| routes | id UUID; vehicle_id UUID; optimization_job_id UUID; total_distance_km NUMERIC; status TEXT; planned_departure TIMESTAMPTZ; planned_arrival TIMESTAMPTZ; created_at TIMESTAMPTZ | PK id; FK vehicle_id, optimization_job_id; status in (active, completed, superseded); planned_departure (the van leaves the depot) and planned_arrival (it reaches JKIA) not null, from the solver's schedule, planned_departure <= planned_arrival |
| route_nodes | id UUID; route_id UUID; pickup_request_id UUID; seq_order INT; estimated_arrival TIMESTAMPTZ; superseded_at TIMESTAMPTZ; created_at TIMESTAMPTZ | PK id; FK route_id, pickup_request_id; pickup_request_id unique among nodes with superseded_at null (partial unique index); route_id and seq_order unique together; superseded_at null until a later job re-plans the pickup |
| pickup_events | id UUID; route_node_id UUID; driver_id UUID; event_type TEXT; exception_type TEXT; confirmed_at TIMESTAMPTZ; synced_at TIMESTAMPTZ; idempotency_key TEXT; created_at TIMESTAMPTZ | PK id; FK route_node_id, driver_id to profiles; event_type in (pickup_confirmed, exception); exception_type in (no_show, vehicle_issue, traffic_delay) or null; idempotency_key unique; at most one pickup_confirmed per route_node_id (partial unique index); synced_at null until synchronised; confirmed_at is when the event **occurred** on the device, for every event type, exceptions included; synced_at is when the server received it |
| trip_records | id UUID; route_node_id UUID; vehicle_id UUID; crew_count INT; pickup_timestamp TIMESTAMPTZ; scheduled_report_time TIMESTAMPTZ; actual_arrival TIMESTAMPTZ; actual_duration_sec INT; day_of_week SMALLINT; route_corridor TEXT; created_at TIMESTAMPTZ | PK id; FK route_node_id (unique), vehicle_id; day_of_week 0 = Monday to 6 = Sunday (see Conventions) |

## Communication model (ERD Figure: communication)

| Table | Columns | Keys and constraints |
|---|---|---|
| preset_messages | id UUID; code TEXT; label TEXT; created_at TIMESTAMPTZ | PK id; code unique |
| crew_messages | id UUID; crew_member_id UUID; preset_message_id UUID; sent_at TIMESTAMPTZ; read_at TIMESTAMPTZ; created_at TIMESTAMPTZ | PK id; FK crew_member_id, preset_message_id; read_at null until reviewed by the dispatcher |
| schedule_change_notices | id UUID; pickup_request_id UUID; reason TEXT; previous_pickup_time TIMESTAMPTZ; new_pickup_time TIMESTAMPTZ; issued_at TIMESTAMPTZ; delivered_at TIMESTAMPTZ; acknowledged_at TIMESTAMPTZ; created_at TIMESTAMPTZ | PK id; FK pickup_request_id; reason in (flight_delay, standby_activation, vehicle_breakdown); pending while acknowledged_at is null |
| device_tokens | id UUID; crew_member_id UUID; fcm_token TEXT; updated_at TIMESTAMPTZ | PK id; FK crew_member_id; fcm_token unique |

## Validation data (not in the Chapter 4 ERD)

Real observed journey times for validating the Random Forest (#21), logged hourly by the
`log-travel-times` Edge Function (#81). Not operational data, so it has no links to the
tables above.

| Table | Columns | Keys and constraints |
|---|---|---|
| travel_time_observations | id UUID; logged_at_utc TIMESTAMPTZ; logged_at_eat TIMESTAMP; day_of_week TEXT; hour_eat SMALLINT; minute_eat SMALLINT; zone TEXT; origin_lat DOUBLE PRECISION; origin_lon DOUBLE PRECISION; element_status TEXT; distance_m INT; duration_sec INT; duration_in_traffic_sec INT; run_id TEXT; created_at TIMESTAMPTZ | PK id; run_id and zone unique together; hour_eat 0 to 23, minute_eat 0 to 59; distance and durations null unless element_status is OK; index on logged_at_utc |

## Reference data (not in the Chapter 4 ERD)

The 28 pickup zones (#52), so a stop can be labelled with its nearest zone in SQL. Copied
unchanged from `data/pickup_zones.csv`, which stays the source the Random Forest loads; a test
checks the two match exactly. No links to other tables: a pickup's zone is the nearest one by
`ST_Distance`.

| Table | Columns | Keys and constraints |
|---|---|---|
| pickup_zones | id UUID; label TEXT; location GEOGRAPHY(Point, 4326); created_at TIMESTAMPTZ | PK id; label unique |

## Relationships

- crew_members 1 to many pickup_requests
- vehicles 1 to many routes; optimization_jobs 1 to many routes; routes 1 to many route_nodes
- pickup_requests 1 to many route_nodes, at most 1 not superseded (the live plan)
- optimization_jobs 1 to many optimization_job_pickups, one per pickup the job was asked to
  place; pickup_requests 1 to many optimization_job_pickups
- route_nodes 1 to many pickup_events: any number of exceptions, at most one `pickup_confirmed`
- route_nodes 1 to at most 1 trip_records (completed leg, feeds Random Forest retraining)
- A driver reaches their route through the vehicle: vehicles.assigned_driver_id
- crew_members 1 to many crew_messages, each from one preset_messages row
- crew_members 1 to many device_tokens
- pickup_requests 1 to many schedule_change_notices

## Row level security

The role lives in `profiles.role`, linked to Supabase Auth. The app also receives route
updates through Supabase Realtime, which enforces these policies, so they are the access rules
for every client path, not only a backstop behind FastAPI.

- **Everyone:** read their own `profiles` row. Dispatchers read all profiles.
- **Dispatcher:** read and write on operational tables; read crew messages and notice status.
- **Driver:** read the route of their assigned vehicle and its route nodes that are not
  superseded; read the `pickup_requests` and `crew_members` rows linked to route nodes on an
  **active** route of that vehicle (who to pick up and where); insert pickup events as
  themselves on a node of a route of that vehicle, judged by when the event happened: a live
  node on an active or completed route, or a superseded node whose `superseded_at` is after
  the event's `confirmed_at` (an offline event synced after a re-plan). Device time is
  evidence, not proof.
- **Dispatcher, validation data:** read `travel_time_observations`. No client writes it: only
  the Edge Function, with the service role.
- **Crew:** read their own pickup requests and notices; read the `route_nodes` for their own
  pickup requests that are not superseded (their current ETA), and the `routes` and `vehicles`
  rows of those nodes (which van is coming); set `acknowledged_at` on their own notices; insert
  their own crew messages; register their own device tokens.
- **Every signed-in user:** read `pickup_zones`. No client writes it.

Policies get the caller's role and any cross-table lookup through `SECURITY DEFINER` functions
(`private.current_app_role()` and similar), never through a subquery on a table that has its
own policies. Policies on `route_nodes` and `pickup_requests` refer to each other, so a direct
subquery would recurse.

The helpers live in the `private` schema, which the Supabase API does not expose, so clients
cannot call them as `/rest/v1/rpc/...` endpoints. Only `authenticated` may execute them; `anon`
and `PUBLIC` may not.

## Triggers (logic outside the API)

- `pickup_events_apply_to_pickup` (after insert on `pickup_events`, `private.apply_pickup_event`,
  `SECURITY DEFINER`, #33) moves the event's pickup request in the same transaction, whatever
  wrote the event:
  - `pickup_confirmed` sets `picked_up` from `assigned` or `missed`;
  - exception `no_show` sets `missed` from `assigned` only;
  - `vehicle_issue` and `traffic_delay` change nothing.

  It never changes a `cancelled` pickup and never moves `picked_up` back. Drivers have no
  UPDATE policy on `pickup_requests`; this is the only way their events change it.
- `pickup_events_drop_stop_collected_elsewhere` (after insert on `pickup_events`,
  `private.drop_stop_collected_elsewhere`, `SECURITY DEFINER`, #113): a `pickup_confirmed` on a
  superseded node (a van collected a pickup it had been re-planned away from) supersedes the
  pickup's live node on another route, unless that node has an event of its own. A route left
  with no live node is marked `superseded`.

## Re-planning (#113)

- A route has **departed** once `planned_departure` has passed, once any of its nodes has a
  pickup event, or once it is `completed`. A re-plan never changes a departed route, except in a
  `vehicle_breakdown` re-plan when its van is `broken_down`: then its pickups not yet past
  `assigned` may move to other vans, and the nodes with events stay.
- A van is **on the road**, and left out of new plans, while it has an `active` route that has
  departed and `planned_arrival` plus a grace period (backend setting, 30 minutes) has not
  passed.
- A re-plan replaces whole routes: the other plannable pickups on a route it touches are planned
  with it. Pickups past `assigned` lose their node and get no new one.

## Conventions

- `day_of_week` (on `trip_records`) is 0 = Monday to 6 = Sunday, the same as Python's
  `datetime.weekday()`. Any SQL that derives it must use `EXTRACT(ISODOW FROM ts) - 1`, never
  `EXTRACT(DOW ...)`: DOW counts Sunday as 0 and would shift every day by one.
- `day_of_week` on `travel_time_observations` is the English day name ("Tuesday"), as the
  logger's CSV wrote it. Convert it before joining with `trip_records`.
- `logged_at_eat` is Nairobi wall-clock time without a zone; `logged_at_utc` is the instant.

## Supabase-provided, not ours

- `public.rls_auto_enable()` backs the `ensure_rls` event trigger that Supabase created with the
  project. It turns RLS on automatically for every new table in `public`. It is not in
  `backend/migrations/`; leave it alone. The security advisor lists it as an executable
  `SECURITY DEFINER` function; that warning is expected.

## Not in the table

- Pickups store their own `pickup_location`, not a zone. The zones are a reference table
  (`pickup_zones`, above) only for labels; `data/pickup_zones.csv` remains the source the
  Random Forest loads. `route_corridor` is a text column on `trip_records`.
- The JKIA terminal coordinate is described as a singleton reference record but has no
  table in Table 4.1. Until decided otherwise it is a backend configuration constant
  (-1.3192, 36.9278).
