-- supabase-only: needs pg_cron, pg_net and Vault, which CI's Postgres lacks.
-- Call the log-travel-times Edge Function hourly at minute 7 (#81), in place
-- of the GitHub Actions schedule, which dropped most runs. pg_cron runs in UTC;
-- minute 7 is the same in EAT.
--
-- The function URL and its secret are read from Vault each time the job runs,
-- so neither is stored here. Both must exist before the first run:
--   select vault.create_secret('https://<project ref>.supabase.co', 'project_url');
--   select vault.create_secret('<LOGGER_SECRET>', 'logger_secret');

create extension if not exists pg_cron with schema pg_catalog;
create extension if not exists pg_net with schema extensions;

select cron.schedule(
    'log-travel-times',
    '7 * * * *',
    $$
    select net.http_post(
        url := (select decrypted_secret from vault.decrypted_secrets where name = 'project_url')
            || '/functions/v1/log-travel-times',
        headers := jsonb_build_object(
            'Content-Type', 'application/json',
            'x-logger-secret',
            (select decrypted_secret from vault.decrypted_secrets where name = 'logger_secret')
        ),
        body := '{}'::jsonb,
        -- Two API calls with up to 6 s of retry backoff can outlast pg_net's
        -- 5 s default.
        timeout_milliseconds := 60000
    );
    $$
);
