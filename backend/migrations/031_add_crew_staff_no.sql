-- The airline's staff number on each crew member (#229), so a roster import
-- can find a crew member it has seen before and update them instead of
-- adding a second record. Nullable: crew added before the import (the seed
-- scripts) have none, and stay valid. Unique, so one staff number is one
-- crew member; Postgres allows any number of nulls under a unique constraint.
alter table public.crew_members
    add column staff_no text unique;
