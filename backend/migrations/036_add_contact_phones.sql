-- Contact numbers for the Call buttons (#255). There is still no chat between
-- crew and driver: a number lets one phone the other, nothing more.
--
-- Drivers' numbers are on profiles; crew numbers on crew_members, because
-- most crew come from the roster import and have no profile. Both are Kenyan
-- mobiles, stored as +2547XXXXXXXX (the import normalises 07..., 254...).
--
-- A number is never readable straight from a table, by anyone signed in:
-- SELECT on the phone columns is revoked from anon and authenticated, so a
-- PostgREST select of phone is a permission error. The only way to one is
-- through the two functions below, which give it only to the other party of
-- a planned pickup, and only from 30 minutes before the scheduled pickup
-- until the pickup is confirmed, missed or cancelled. The backend's reads
-- (app/reads.py) call them; the app never sees a number outside that window.
--
-- Column-level SELECT means every other column is granted by name here. A
-- later migration that adds a column to either table must grant it too.

alter table public.profiles
    add column phone text constraint profiles_phone_kenyan_mobile
        check (phone ~ '^\+2547[0-9]{8}$');

alter table public.crew_members
    add column phone text constraint crew_members_phone_kenyan_mobile
        check (phone ~ '^\+2547[0-9]{8}$');

revoke select on public.profiles from anon, authenticated;
grant select (id, role, full_name, created_at) on public.profiles to anon, authenticated;

revoke select on public.crew_members from anon, authenticated;
grant select (id, profile_id, name, role, home_location, staff_no, created_at)
    on public.crew_members to anon, authenticated;

-- For the crew member signed in: their pickup's driver's first name (from
-- when a route plans the pickup) and number (only in the window). No row
-- for another crew member's pickup, or one no live route node plans.
create function private.driver_contact(pickup_request_id uuid)
returns table (first_name text, phone text)
language sql stable security definer set search_path = ''
as $$
    select split_part(d.full_name, ' ', 1),
        case
            when p.status in ('pending', 'assigned')
                and now() >= n.estimated_arrival - interval '30 minutes'
            then d.phone
        end
    from public.pickup_requests p
    join public.crew_members c on c.id = p.crew_member_id
    join public.route_nodes n on n.pickup_request_id = p.id and n.superseded_at is null
    join public.routes r on r.id = n.route_id
    join public.vehicles v on v.id = r.vehicle_id
    join public.profiles d on d.id = v.assigned_driver_id
    where p.id = driver_contact.pickup_request_id
      and c.profile_id = (select auth.uid())
$$;

-- For the driver signed in: the crew member's number at one of their live
-- stops, only in the window; null otherwise, and for another van's stop.
create function private.crew_phone(route_node_id uuid)
returns text
language sql stable security definer set search_path = ''
as $$
    select case
            when p.status in ('pending', 'assigned')
                and now() >= n.estimated_arrival - interval '30 minutes'
            then c.phone
        end
    from public.route_nodes n
    join public.routes r on r.id = n.route_id
    join public.vehicles v on v.id = r.vehicle_id
    join public.pickup_requests p on p.id = n.pickup_request_id
    join public.crew_members c on c.id = p.crew_member_id
    where n.id = crew_phone.route_node_id
      and n.superseded_at is null
      and v.assigned_driver_id = (select auth.uid())
$$;

revoke execute on function private.driver_contact(uuid), private.crew_phone(uuid)
    from public, anon;
grant execute on function private.driver_contact(uuid), private.crew_phone(uuid)
    to authenticated;
