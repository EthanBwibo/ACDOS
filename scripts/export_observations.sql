-- ACDOS: snapshot of travel_time_observations for the Random Forest
-- validation (#103, backend/benchmarks/rf_validation.py).
--
-- Every OK row logged before the cutoff, as data/travel_time_observations.csv.
-- Run from the repo root; the connection string comes from the environment,
-- never from this file:
--
--   psql "$SUPABASE_DB_URL" -v cutoff='2026-11-10T00:00:00+00' -f scripts/export_observations.sql
--
-- The cutoff is an instant (timestamptz) compared with logged_at_utc, so the
-- same cutoff always gives the same rows. Times are written as text in fixed
-- formats so the file does not depend on the session's DateStyle or TimeZone.
-- No coordinates (they are the zones' own, data/pickup_zones.csv) and no
-- personal data.

\set ON_ERROR_STOP on

-- psql does not expand variables inside \copy, hence the view.
create temporary view observation_snapshot as
select
    to_char(logged_at_utc at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') as logged_at_utc,
    to_char(logged_at_eat, 'YYYY-MM-DD"T"HH24:MI:SS') as logged_at_eat,
    day_of_week,
    hour_eat,
    minute_eat,
    zone,
    distance_m,
    duration_sec,
    duration_in_traffic_sec,
    run_id
from travel_time_observations
where logged_at_utc < :'cutoff'::timestamptz
  and element_status = 'OK'
order by travel_time_observations.logged_at_utc, zone;

\copy (select * from observation_snapshot) to 'data/travel_time_observations.csv' with (format csv, header)
