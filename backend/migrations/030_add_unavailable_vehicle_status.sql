-- A van can be taken out of planning without being broken down (#198):
-- 'unavailable'. The planner refuses it and the dispatcher's van picker skips
-- it, like broken_down, but it raises no breakdown alert. The demo seed uses
-- it for the test vans (KDA 001T, KDA 002T), so the defence's picker cannot
-- offer them and the hub's Alerts show only the real breakdown.
alter table public.vehicles
    drop constraint vehicles_status_check,
    add constraint vehicles_status_check
        check (status in ('available', 'in_service', 'broken_down', 'unavailable'));
