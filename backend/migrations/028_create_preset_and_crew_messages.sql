-- Crew-to-dispatcher preset messages (#54, minimal). As in docs/schema.md
-- (Table 4.1, communication model), plus crew_messages.idempotency_key.
--
-- Free text is ruled out by the schema: a crew message is a reference to a
-- preset, never a text body. Every message goes to the dispatcher; there
-- is no crew-to-crew or crew-to-driver channel, and drivers see nothing
-- here. Messages never trigger re-optimisation: nothing reads them but the
-- dispatcher's screen.

create table public.preset_messages (
    id uuid primary key default gen_random_uuid(),
    code text not null unique,
    label text not null,
    created_at timestamptz not null default now()
);

-- The fixed set the crew app offers. Codes are what clients send; labels
-- are what both screens show.
insert into public.preset_messages (code, label) values
    ('running_late', 'I am running late'),
    ('at_pickup_point', 'I am at the pickup point'),
    ('cannot_find_van', 'I cannot find the van'),
    ('flight_changed', 'My flight has changed'),
    ('please_call_me', 'Please call me');

create table public.crew_messages (
    id uuid primary key default gen_random_uuid(),
    crew_member_id uuid not null references public.crew_members (id),
    preset_message_id uuid not null references public.preset_messages (id),
    sent_at timestamptz not null default now(),
    -- Null until the dispatcher has reviewed it.
    read_at timestamptz,
    -- From the crew app's Idempotency-Key header: a retried send on a weak
    -- connection finds the message it already made instead of a second one.
    idempotency_key text not null unique,
    created_at timestamptz not null default now()
);

create index crew_messages_crew_member_id_idx on public.crew_messages (crew_member_id);
create index crew_messages_preset_message_id_idx on public.crew_messages (preset_message_id);
-- The dispatcher's list, newest first.
create index crew_messages_sent_at_idx on public.crew_messages (sent_at desc, id desc);

alter table public.preset_messages enable row level security;
alter table public.crew_messages enable row level security;

-- Presets: read by crew and the dispatcher; written only by migrations.
create policy preset_messages_crew_dispatcher_select on public.preset_messages
    for select to authenticated
    using ((select private.current_app_role()) in ('crew', 'dispatcher'));

-- Crew: send their own messages, unread, and read them back.
create policy crew_messages_crew_insert on public.crew_messages
    for insert to authenticated
    with check (
        (select private.current_app_role()) = 'crew'
        and crew_member_id = (select private.current_crew_member_id())
        and read_at is null
    );

create policy crew_messages_crew_select on public.crew_messages
    for select to authenticated
    using (crew_member_id = (select private.current_crew_member_id()));

-- Crew read their own crew_members row, so their message list can carry
-- their name like the dispatcher's does. Nobody else's.
create policy crew_members_crew_select_own on public.crew_members
    for select to authenticated
    using (id = (select private.current_crew_member_id()));

-- Dispatcher: read every message and mark it read.
create policy crew_messages_dispatcher_select on public.crew_messages
    for select to authenticated
    using ((select private.current_app_role()) = 'dispatcher');

create policy crew_messages_dispatcher_read on public.crew_messages
    for update to authenticated
    using ((select private.current_app_role()) = 'dispatcher')
    with check ((select private.current_app_role()) = 'dispatcher' and read_at is not null);

-- The policies decide rows; the grants decide what a client may do at all.
-- Presets are read-only. A message can be sent (inserted) but never edited
-- or deleted, except read_at, the one column the dispatcher sets.
revoke insert, update, delete, truncate on public.preset_messages from anon, authenticated;
revoke insert, update, delete, truncate on public.crew_messages from anon, authenticated;
grant insert on public.crew_messages to authenticated;
grant update (read_at) on public.crew_messages to authenticated;
