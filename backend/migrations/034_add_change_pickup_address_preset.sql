-- A crew preset to ask for a new pickup address (#232).
--
-- It reaches the dispatcher like any other crew preset. It never triggers a
-- re-plan and changes no data: not crew_members.home_location, not any
-- pickup. The roster is the source of truth for where crew are collected
-- (each pickup row carries its own pickup point), so the dispatcher makes
-- the change in the next roster import. Crew only (sender 'crew'); drivers
-- see no presets at all.

insert into public.preset_messages (code, label, sender) values
    ('change_pickup_address', 'I need to change my pickup address', 'crew');
