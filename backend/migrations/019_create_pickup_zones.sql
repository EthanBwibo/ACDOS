-- The 28 pickup zones as a table (#52), so the driver's route can label each
-- stop with its nearest zone in SQL (PostGIS), not in the API layer.
--
-- data/pickup_zones.csv stays the source: the Random Forest and the zone
-- matrix load it, and tests/test_driver_crew_reads_postgres.py checks this
-- table matches it exactly (labels and points). Rows copied from the CSV
-- unchanged, in its order.
create table public.pickup_zones (
    id uuid primary key default gen_random_uuid(),
    label text not null unique,
    location geography(Point, 4326) not null,
    created_at timestamptz not null default now()
);

insert into public.pickup_zones (label, location) values
    ('South B, Nairobi', 'SRID=4326;POINT(36.833737 -1.310341)'),
    ('South C, Nairobi', 'SRID=4326;POINT(36.828893 -1.322274)'),
    ('Embakasi, Nairobi', 'SRID=4326;POINT(36.899962 -1.323786)'),
    ('Imara Daima, Nairobi', 'SRID=4326;POINT(36.88065 -1.328436)'),
    ('Nyayo Estate, Nairobi', 'SRID=4326;POINT(36.904456 -1.307259)'),
    ('Karen, Nairobi', 'SRID=4326;POINT(36.667803 -1.323994)'),
    ('Lavington, Nairobi', 'SRID=4326;POINT(36.777798 -1.278937)'),
    ('Kilimani, Nairobi', 'SRID=4326;POINT(36.786931 -1.289279)'),
    ('Westlands, Nairobi', 'SRID=4326;POINT(36.812022 -1.2675)'),
    ('Runda, Nairobi', 'SRID=4326;POINT(36.815044 -1.215566)'),
    ('Buruburu, Nairobi', 'SRID=4326;POINT(36.881548 -1.292248)'),
    ('Donholm, Nairobi', 'SRID=4326;POINT(36.897118 -1.293916)'),
    ('Langata, Nairobi', 'SRID=4326;POINT(36.747626 -1.364094)'),
    ('Ruiru, Kiambu County', 'SRID=4326;POINT(36.960578 -1.148378)'),
    ('Ongata Rongai, Kajiado County', 'SRID=4326;POINT(36.744238 -1.393864)'),
    ('Kitengela, Kajiado County', 'SRID=4326;POINT(36.957676 -1.478682)'),
    ('Athi River, Machakos County', 'SRID=4326;POINT(36.978503 -1.457725)'),
    ('Kasarani, Nairobi', 'SRID=4326;POINT(36.897637 -1.225399)'),
    ('Roysambu, Nairobi', 'SRID=4326;POINT(36.887962 -1.216019)'),
    ('Kahawa, Nairobi', 'SRID=4326;POINT(36.916667 -1.183333)'),
    ('Dagoretti, Nairobi', 'SRID=4326;POINT(36.728069 -1.288983)'),
    ('Kawangware, Nairobi', 'SRID=4326;POINT(36.752365 -1.282272)'),
    ('Umoja, Nairobi', 'SRID=4326;POINT(36.905729 -1.274357)'),
    ('Kayole, Nairobi', 'SRID=4326;POINT(36.915798 -1.277394)'),
    ('Mlolongo, Machakos County', 'SRID=4326;POINT(36.938489 -1.38872)'),
    ('Nairobi CBD, Nairobi', 'SRID=4326;POINT(36.821946 -1.292066)'),
    ('Upper Hill, Nairobi', 'SRID=4326;POINT(36.813231 -1.298356)'),
    ('Ngara, Nairobi', 'SRID=4326;POINT(36.830417 -1.278124)');

-- Reference data, not personal: any signed-in user may read it. No client
-- writes it.
alter table public.pickup_zones enable row level security;

revoke insert, update, delete, truncate on public.pickup_zones from anon, authenticated;

create policy pickup_zones_authenticated_select on public.pickup_zones
    for select to authenticated
    using (true);
