-- Covering indexes for the two foreign keys without one (Supabase advisor
-- lint 0001, #64). Without them, deleting or updating a profile or vehicle
-- scans the whole child table to check the reference.

-- Dispatcher views of events by driver.
create index pickup_events_driver_id_idx on public.pickup_events (driver_id);

-- Random Forest and benchmarking queries group trips by vehicle.
create index trip_records_vehicle_id_idx on public.trip_records (vehicle_id);
