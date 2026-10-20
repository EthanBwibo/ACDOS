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
| optimization_jobs | id UUID; triggered_at TIMESTAMPTZ; trigger_type TEXT; status TEXT; created_at TIMESTAMPTZ | PK id; trigger_type in (scheduled, flight_delay, standby_activation, vehicle_breakdown); status in (running, completed, failed) |
| pickup_requests | id UUID; crew_member_id UUID; pickup_location GEOGRAPHY(Point, 4326); report_time TIMESTAMPTZ; request_type TEXT; status TEXT; created_at TIMESTAMPTZ | PK id; FK crew_member_id; request_type in (rostered, standby); status in (pending, assigned, picked_up, missed, cancelled); spatial index on pickup_location |
| routes | id UUID; vehicle_id UUID; optimization_job_id UUID; total_distance_km NUMERIC; status TEXT; created_at TIMESTAMPTZ | PK id; FK vehicle_id, optimization_job_id; status in (active, completed, superseded) |
| route_nodes | id UUID; route_id UUID; pickup_request_id UUID; seq_order INT; estimated_arrival TIMESTAMPTZ; created_at TIMESTAMPTZ | PK id; FK route_id, pickup_request_id (unique); route_id and seq_order unique together |
| pickup_events | id UUID; route_node_id UUID; driver_id UUID; event_type TEXT; exception_type TEXT; confirmed_at TIMESTAMPTZ; synced_at TIMESTAMPTZ; idempotency_key TEXT; created_at TIMESTAMPTZ | PK id; FK route_node_id, driver_id to profiles; event_type in (pickup_confirmed, exception); exception_type in (no_show, vehicle_issue, traffic_delay) or null; idempotency_key unique; at most one pickup_confirmed per route_node_id (partial unique index); synced_at null until synchronised |
| trip_records | id UUID; route_node_id UUID; vehicle_id UUID; crew_count INT; pickup_timestamp TIMESTAMPTZ; scheduled_report_time TIMESTAMPTZ; actual_arrival TIMESTAMPTZ; actual_duration_sec INT; day_of_week SMALLINT; route_corridor TEXT; created_at TIMESTAMPTZ | PK id; FK route_node_id (unique), vehicle_id |

## Communication model (ERD Figure: communication)

| Table | Columns | Keys and constraints |
|---|---|---|
| preset_messages | id UUID; code TEXT; label TEXT; created_at TIMESTAMPTZ | PK id; code unique |
| crew_messages | id UUID; crew_member_id UUID; preset_message_id UUID; sent_at TIMESTAMPTZ; read_at TIMESTAMPTZ; created_at TIMESTAMPTZ | PK id; FK crew_member_id, preset_message_id; read_at null until reviewed by the dispatcher |
| schedule_change_notices | id UUID; pickup_request_id UUID; reason TEXT; previous_pickup_time TIMESTAMPTZ; new_pickup_time TIMESTAMPTZ; issued_at TIMESTAMPTZ; delivered_at TIMESTAMPTZ; acknowledged_at TIMESTAMPTZ; created_at TIMESTAMPTZ | PK id; FK pickup_request_id; reason in (flight_delay, standby_activation, vehicle_breakdown); pending while acknowledged_at is null |
| device_tokens | id UUID; crew_member_id UUID; fcm_token TEXT; updated_at TIMESTAMPTZ | PK id; FK crew_member_id; fcm_token unique |

## Relationships

- crew_members 1 to many pickup_requests
- vehicles 1 to many routes; optimization_jobs 1 to many routes; routes 1 to many route_nodes
- pickup_requests 1 to at most 1 route_nodes
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
- **Driver:** read the route of their assigned vehicle; read the `pickup_requests` and
  `crew_members` rows linked to route nodes on an **active** route of that vehicle (who to pick
  up and where); insert pickup events.
- **Crew:** read their own pickup requests and notices; read the `route_nodes` for their own
  pickup requests (their ETA); set `acknowledged_at` on their own notices; insert their own crew
  messages; register their own device tokens.

Policies get the caller's role and any cross-table lookup through `SECURITY DEFINER` functions
(`public.current_app_role()` and similar), never through a subquery on a table that has its
own policies. Policies on `route_nodes` and `pickup_requests` refer to each other, so a direct
subquery would recurse.

## Not in the table

- Pickup zones are not a table. `data/pickup_zones.csv` feeds the Random Forest only;
  pickups store their own `pickup_location`. `route_corridor` is a text column on
  `trip_records`.
- The JKIA terminal coordinate is described as a singleton reference record but has no
  table in Table 4.1. Until decided otherwise it is a backend configuration constant
  (-1.3192, 36.9278).
