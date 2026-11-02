-- supabase-only: needs pg_cron, which CI's Postgres lacks.
-- Stop the hourly travel-time logger (015) on 8 November 2026 at 05:00 UTC
-- (08:00 EAT): a one-off pg_cron job unschedules log-travel-times, then
-- itself. This keeps the Google Distance Matrix calls within the free tier;
-- the observations logged until then are the validation data.
--
-- Applied to Supabase on 2 November 2026 before it was in git (#143). The
-- statement below is byte for byte the one in Supabase's migration history
-- (supabase_migrations.schema_migrations, version 20261102085622), so the
-- file matches production: md5 of the statement is
-- 46a35242bfc09422f69fbc89fa543ec6.

select cron.schedule(
    'stop-travel-time-logger',
    '0 5 8 11 *',
    $$
    select cron.unschedule('log-travel-times');
    select cron.unschedule('stop-travel-time-logger');
    $$
);
