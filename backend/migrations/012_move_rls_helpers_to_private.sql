-- Move the RLS helper functions from public to a private schema (#64).
--
-- In public they are exposed as /rest/v1/rpc/<name>, callable even without
-- signing in (Supabase advisor lints 0028/0029). The Supabase API does not
-- expose the private schema, so policies can still call them but clients
-- cannot. Only authenticated may execute them: every policy that uses them
-- is "to authenticated", and policies run with the caller's privileges.
--
-- Order: create the new functions, point the policies at them, then drop the
-- old ones. The drops have no CASCADE, so they fail if a policy was missed.

create schema private;

-- Functions get EXECUTE for PUBLIC by default; take that away for anything
-- created in this schema from now on.
alter default privileges in schema private revoke execute on functions from public;
grant usage on schema private to authenticated;

-- Same bodies as in 011, but every helper-to-helper call uses private.

-- The caller's role from profiles, or null when not signed in.
create function private.current_app_role() returns text
language sql stable security definer set search_path = ''
as $$
    select role from public.profiles where id = auth.uid();
$$;

-- The caller's crew_members.id, or null if they are not crew.
create function private.current_crew_member_id() returns uuid
language sql stable security definer set search_path = ''
as $$
    select id from public.crew_members where profile_id = auth.uid();
$$;

-- Pickup requests on active routes of the vehicle the caller drives.
create function private.driver_active_pickup_request_ids() returns setof uuid
language sql stable security definer set search_path = ''
as $$
    select n.pickup_request_id
    from public.route_nodes n
    join public.routes r on r.id = n.route_id
    join public.vehicles v on v.id = r.vehicle_id
    where r.status = 'active'
      and v.assigned_driver_id = auth.uid();
$$;

-- Crew members behind those pickup requests.
create function private.driver_active_crew_member_ids() returns setof uuid
language sql stable security definer set search_path = ''
as $$
    select p.crew_member_id
    from public.pickup_requests p
    where p.id in (select private.driver_active_pickup_request_ids());
$$;

-- Pickup requests that belong to the calling crew member.
create function private.crew_pickup_request_ids() returns setof uuid
language sql stable security definer set search_path = ''
as $$
    select p.id
    from public.pickup_requests p
    join public.crew_members c on c.id = p.crew_member_id
    where c.profile_id = auth.uid();
$$;

-- Explicit as well as the default above, so the grants are readable here.
revoke execute on function
    private.current_app_role(),
    private.current_crew_member_id(),
    private.driver_active_pickup_request_ids(),
    private.driver_active_crew_member_ids(),
    private.crew_pickup_request_ids()
from public, anon;

grant execute on function
    private.current_app_role(),
    private.current_crew_member_id(),
    private.driver_active_pickup_request_ids(),
    private.driver_active_crew_member_ids(),
    private.crew_pickup_request_ids()
to authenticated;

-- Point the 13 policies that use a helper at the private versions.

alter policy profiles_dispatcher_select on public.profiles
    using ((select private.current_app_role()) = 'dispatcher');

alter policy crew_members_dispatcher_all on public.crew_members
    using ((select private.current_app_role()) = 'dispatcher')
    with check ((select private.current_app_role()) = 'dispatcher');

alter policy vehicles_dispatcher_all on public.vehicles
    using ((select private.current_app_role()) = 'dispatcher')
    with check ((select private.current_app_role()) = 'dispatcher');

alter policy optimization_jobs_dispatcher_all on public.optimization_jobs
    using ((select private.current_app_role()) = 'dispatcher')
    with check ((select private.current_app_role()) = 'dispatcher');

alter policy pickup_requests_dispatcher_all on public.pickup_requests
    using ((select private.current_app_role()) = 'dispatcher')
    with check ((select private.current_app_role()) = 'dispatcher');

alter policy routes_dispatcher_all on public.routes
    using ((select private.current_app_role()) = 'dispatcher')
    with check ((select private.current_app_role()) = 'dispatcher');

alter policy route_nodes_dispatcher_all on public.route_nodes
    using ((select private.current_app_role()) = 'dispatcher')
    with check ((select private.current_app_role()) = 'dispatcher');

alter policy pickup_events_dispatcher_all on public.pickup_events
    using ((select private.current_app_role()) = 'dispatcher')
    with check ((select private.current_app_role()) = 'dispatcher');

alter policy trip_records_dispatcher_all on public.trip_records
    using ((select private.current_app_role()) = 'dispatcher')
    with check ((select private.current_app_role()) = 'dispatcher');

alter policy pickup_requests_driver_select on public.pickup_requests
    using (id in (select private.driver_active_pickup_request_ids()));

alter policy crew_members_driver_select on public.crew_members
    using (id in (select private.driver_active_crew_member_ids()));

alter policy pickup_requests_crew_select on public.pickup_requests
    using (crew_member_id = (select private.current_crew_member_id()));

alter policy route_nodes_crew_select on public.route_nodes
    using (pickup_request_id in (select private.crew_pickup_request_ids()));

-- Nothing refers to the public versions any more.
drop function public.driver_active_crew_member_ids();
drop function public.driver_active_pickup_request_ids();
drop function public.crew_pickup_request_ids();
drop function public.current_crew_member_id();
drop function public.current_app_role();
