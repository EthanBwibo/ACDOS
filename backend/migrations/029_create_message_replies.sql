-- The dispatcher's preset replies to crew messages. Like a crew message, a
-- reply is a reference to a preset and never a text body, so free text stays
-- ruled out by the schema. A reply goes only to the crew member who sent the
-- message; drivers see nothing here. Replies never trigger re-optimisation.

-- Who may send each preset: the crew's existing set, or the new replies.
alter table public.preset_messages
    add column sender text not null default 'crew'
        check (sender in ('crew', 'dispatcher'));

insert into public.preset_messages (code, label, sender) values
    ('noted', 'Noted', 'dispatcher'),
    ('van_rerouted', 'Van rerouted', 'dispatcher'),
    ('call_dispatcher', 'Call the dispatcher', 'dispatcher');

create table public.message_replies (
    id uuid primary key default gen_random_uuid(),
    -- A reply has no meaning without its message, so it goes with it.
    crew_message_id uuid not null references public.crew_messages (id) on delete cascade,
    preset_message_id uuid not null references public.preset_messages (id),
    dispatcher_id uuid not null references public.profiles (id),
    sent_at timestamptz not null default now(),
    -- From the dispatcher app's Idempotency-Key header, as on crew_messages.
    idempotency_key text not null unique,
    created_at timestamptz not null default now()
);

create index message_replies_crew_message_id_idx on public.message_replies (crew_message_id);
create index message_replies_preset_message_id_idx on public.message_replies (preset_message_id);
create index message_replies_dispatcher_id_idx on public.message_replies (dispatcher_id);

alter table public.message_replies enable row level security;

-- Dispatcher: send replies as themselves, using reply presets only.
create policy message_replies_dispatcher_insert on public.message_replies
    for insert to authenticated
    with check (
        (select private.current_app_role()) = 'dispatcher'
        and dispatcher_id = (select auth.uid())
        and exists (
            select 1 from public.preset_messages p
            where p.id = preset_message_id and p.sender = 'dispatcher'
        )
    );

create policy message_replies_dispatcher_select on public.message_replies
    for select to authenticated
    using ((select private.current_app_role()) = 'dispatcher');

-- Crew: read the replies to their own messages. The join is filtered by
-- crew_messages' own RLS as well.
create policy message_replies_crew_select on public.message_replies
    for select to authenticated
    using (
        exists (
            select 1 from public.crew_messages m
            where m.id = crew_message_id
              and m.crew_member_id = (select private.current_crew_member_id())
        )
    );

-- Crew may now only send crew presets.
drop policy crew_messages_crew_insert on public.crew_messages;
create policy crew_messages_crew_insert on public.crew_messages
    for insert to authenticated
    with check (
        (select private.current_app_role()) = 'crew'
        and crew_member_id = (select private.current_crew_member_id())
        and read_at is null
        and exists (
            select 1 from public.preset_messages p
            where p.id = preset_message_id and p.sender = 'crew'
        )
    );

-- A reply can be sent but never edited or deleted.
revoke insert, update, delete, truncate on public.message_replies from anon, authenticated;
grant insert on public.message_replies to authenticated;
