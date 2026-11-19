-- Add pickup (#253): a pickup the dispatcher adds by hand, keyed by the
-- app's Idempotency-Key header, so a retry on a bad connection gets the pickup
-- it already made instead of a second one. Pickups from the roster import and
-- the seed scripts have neither column (null; unique allows many nulls).

alter table public.pickup_requests
    add column idempotency_key text unique,
    -- SHA-256 of the request body: the same key with a different body is
    -- refused, not answered with the first pickup.
    add column request_hash text,
    add constraint pickup_requests_idempotency_pair
        check ((idempotency_key is null) = (request_hash is null));
