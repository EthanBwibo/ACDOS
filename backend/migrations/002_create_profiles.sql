-- One row per Supabase Auth user. profiles.role is what RLS uses to decide
-- what each user can see, so the app never asks the user to pick a role.
create table public.profiles (
    id uuid primary key references auth.users (id) on delete cascade,
    role text not null check (role in ('dispatcher', 'driver', 'crew')),
    full_name text not null,
    created_at timestamptz not null default now()
);
