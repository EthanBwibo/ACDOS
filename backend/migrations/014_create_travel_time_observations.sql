-- Hourly Google Distance Matrix observations, pickup zone to JKIA (#81).
-- The real journey times the Random Forest is validated against (#21).
-- Written only by the log-travel-times Edge Function, with the service role;
-- dispatchers can read. Not part of the Chapter 4 ERD: validation data, not
-- operational data.
--
-- Columns match travel_time_log.csv, which the GitHub Actions logger wrote on
-- the data-logger branch, so its rows import unchanged.
create table public.travel_time_observations (
    id uuid primary key default gen_random_uuid(),
    logged_at_utc timestamptz not null,
    -- The same instant as Nairobi wall-clock time, no time zone.
    logged_at_eat timestamp not null,
    day_of_week text not null,
    hour_eat smallint not null check (hour_eat between 0 and 23),
    minute_eat smallint not null check (minute_eat between 0 and 59),
    zone text not null,
    origin_lat double precision not null,
    origin_lon double precision not null,
    element_status text not null,
    -- Null unless element_status is 'OK'.
    distance_m int,
    duration_sec int,
    duration_in_traffic_sec int,
    -- GitHub Actions run id for imported rows, 'edge-<UTC time>' from Supabase.
    run_id text not null,
    created_at timestamptz not null default now(),
    -- One row per zone per run, so an import can be re-run safely.
    unique (run_id, zone)
);

create index travel_time_observations_logged_at_utc_idx
    on public.travel_time_observations (logged_at_utc);

alter table public.travel_time_observations enable row level security;

-- No client writes: no write policy, and the grants are taken away too.
revoke insert, update, delete, truncate on public.travel_time_observations
    from anon, authenticated;

create policy travel_time_observations_dispatcher_select on public.travel_time_observations
    for select to authenticated
    using ((select private.current_app_role()) = 'dispatcher');
