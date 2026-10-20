-- Rostered crew. profile_id is null until the crew member has an app account,
-- and unique so one account maps to at most one crew record.
create table public.crew_members (
    id uuid primary key default gen_random_uuid(),
    profile_id uuid unique references public.profiles (id),
    name text not null,
    role text not null,
    home_location geography(Point, 4326) not null,
    created_at timestamptz not null default now()
);
