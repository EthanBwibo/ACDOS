-- What the optimisation job API (#51) needs on each job row.
--
-- status gains 'queued': the job is accepted but waits for a free solver
-- process; 'running' means a process has it. New jobs start queued.
--
-- idempotency_key is the client's Idempotency-Key header, so a retried POST
-- returns the job it already started instead of starting a second one.
-- request_hash is a SHA-256 of the request body: the same key with a
-- different body is a client bug, and the API refuses it.
--
-- error says why a failed job failed; finished_at is when it completed or
-- failed. Both stay null while it is queued or running.
alter table public.optimization_jobs
    drop constraint optimization_jobs_status_check;

alter table public.optimization_jobs
    add constraint optimization_jobs_status_check
    check (status in ('queued', 'running', 'completed', 'failed'));

alter table public.optimization_jobs
    alter column status set default 'queued';

-- Jobs made before the API have no key: nullable, and unique only where set.
alter table public.optimization_jobs
    add column idempotency_key text unique;

alter table public.optimization_jobs
    add column request_hash text;

alter table public.optimization_jobs
    add column error text;

alter table public.optimization_jobs
    add column finished_at timestamptz;
