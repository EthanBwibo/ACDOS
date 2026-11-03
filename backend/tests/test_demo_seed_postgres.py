"""The demo seed (benchmarks/demo_seed.py) against Postgres with the
migrations: seed then reset leaves every table as it was, seeding is
idempotent, and non-demo rows are never touched.

They insert auth.users rows for driver@ and crew@, so they run only on a
throwaway database: when DATABASE_URL is set in the environment (CI's
PostGIS service), never against a Supabase host.

Each test seeds the accounts and a non-demo bystander (a van, a crew member,
a pickup and a planned route), with fresh ids, deleted afterwards by id.
"""

import asyncio
import os
from datetime import date, datetime, timedelta
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import asyncpg
import pytest

from benchmarks import demo_seed
from benchmarks.demo_seed import EAT, MixedDemoData

DATABASE_URL = os.environ.get("DATABASE_URL")
pytestmark = [
    pytest.mark.skipif(not DATABASE_URL, reason="needs DATABASE_URL in the environment"),
    pytest.mark.skipif(
        bool(DATABASE_URL) and "supabase" in (urlsplit(DATABASE_URL).hostname or ""),
        reason="inserts auth.users rows: never against Supabase",
    ),
]

RUN = uuid4().hex[:8]
DAY = date(2030, 3, 14)
HOME = "SRID=4326;POINT(36.812 -1.2675)"

TABLES = [
    "auth.users",
    "public.profiles",
    "public.crew_members",
    "public.vehicles",
    "public.pickup_requests",
    "public.optimization_jobs",
    "public.optimization_job_pickups",
    "public.routes",
    "public.route_nodes",
    "public.pickup_events",
    "public.trip_records",
    "public.schedule_change_notices",
    "public.crew_messages",
    "public.preset_messages",
    "public.pickup_zones",
]


def db(query):
    async def run():
        conn = await asyncpg.connect(DATABASE_URL, statement_cache_size=0)
        try:
            return await query(conn)
        finally:
            await conn.close()

    return asyncio.run(run())


async def snapshot(conn, without: str = "") -> dict[str, list[str]]:
    """Every row of TABLES as JSON, optionally without one column."""
    return {
        t: [
            r[0]
            for r in await conn.fetch(
                f"select (to_jsonb(t) - $1::text)::text from {t} t order by 1", without
            )
        ]
        for t in TABLES
    }


async def plan(conn, vans: list[UUID], pickups: list[UUID], trigger="scheduled") -> UUID:
    """A completed job with one route per van, the pickups spread over them."""
    job = await conn.fetchval(
        "insert into public.optimization_jobs (trigger_type, status, idempotency_key) "
        "values ($1, 'completed', $2) returning id",
        trigger,
        f"test-{RUN}-{uuid4().hex}",
    )
    start = datetime.combine(DAY, datetime.min.time(), EAT) + timedelta(hours=4)
    routes = [
        await conn.fetchval(
            "insert into public.routes (vehicle_id, optimization_job_id, total_distance_km, "
            "planned_departure, planned_arrival) values ($1, $2, 20, $3, $4) returning id",
            van,
            job,
            start,
            start + timedelta(hours=2),
        )
        for van in vans
    ]
    for i, pickup in enumerate(pickups):
        await conn.execute(
            "insert into public.route_nodes (route_id, pickup_request_id, seq_order, "
            "estimated_arrival) values ($1, $2, $3, $4)",
            routes[i % len(routes)],
            pickup,
            i,
            start + timedelta(minutes=10 * i),
        )
        await conn.execute(
            "insert into public.optimization_job_pickups "
            "(optimization_job_id, pickup_request_id, outcome, late_sec) "
            "values ($1, $2, 'on_time', 0)",
            job,
            pickup,
        )
    return job


class World:
    def __init__(self) -> None:
        self.driver, self.crew_user = uuid4(), uuid4()
        self.crew_member: UUID | None = None
        self.van: UUID | None = None
        self.bystander_crew: UUID | None = None
        self.pickup: UUID | None = None
        self.job: UUID | None = None


async def seed_world(conn, w: World) -> None:
    async with conn.transaction():
        for uid, email, role in [
            (w.driver, demo_seed.DRIVER_EMAIL, "driver"),
            (w.crew_user, demo_seed.CREW_EMAIL, "crew"),
        ]:
            await conn.execute("insert into auth.users (id, email) values ($1, $2)", uid, email)
            await conn.execute(
                "insert into public.profiles (id, role, full_name) values ($1, $2, $3)",
                uid,
                role,
                f"test-{RUN} {role}",
            )
        w.crew_member = await conn.fetchval(
            "insert into public.crew_members (profile_id, name, role, home_location) "
            "values ($1, $2, 'cabin_crew', $3) returning id",
            w.crew_user,
            f"test-{RUN} crew",
            HOME,
        )
        # The bystander: driver@'s non-demo van with a planned route.
        w.van = await conn.fetchval(
            "insert into public.vehicles (assigned_driver_id, plate_number, capacity) "
            "values ($1, $2, 4) returning id",
            w.driver,
            f"test-{RUN}",
        )
        w.bystander_crew = await conn.fetchval(
            "insert into public.crew_members (name, role, home_location) "
            "values ($1, 'cabin_crew', $2) returning id",
            f"test-{RUN} bystander",
            HOME,
        )
        w.pickup = await conn.fetchval(
            "insert into public.pickup_requests (crew_member_id, pickup_location, report_time, "
            "request_type, status) values ($1, $2, $3, 'rostered', 'assigned') returning id",
            w.bystander_crew,
            HOME,
            datetime.combine(DAY, datetime.min.time(), EAT) + timedelta(hours=6),
        )
        w.job = await plan(conn, [w.van], [w.pickup])


async def clean_world(conn, w: World) -> None:
    async with conn.transaction():
        if w.job:
            await conn.execute(
                "delete from public.route_nodes where route_id in "
                "(select id from public.routes where optimization_job_id = $1)",
                w.job,
            )
            await conn.execute(
                "delete from public.optimization_job_pickups where optimization_job_id = $1",
                w.job,
            )
            await conn.execute("delete from public.routes where optimization_job_id = $1", w.job)
            await conn.execute("delete from public.optimization_jobs where id = $1", w.job)
        await conn.execute("delete from public.pickup_requests where id = $1", w.pickup)
        await conn.execute(
            "delete from public.crew_members where id = any($1)", [w.crew_member, w.bystander_crew]
        )
        await conn.execute("delete from public.vehicles where id = $1", w.van)
        users = [w.driver, w.crew_user]
        await conn.execute("delete from public.profiles where id = any($1)", users)
        await conn.execute("delete from auth.users where id = any($1)", users)


@pytest.fixture
def world():
    w = World()
    try:
        db(lambda conn: seed_world(conn, w))
        yield w
    finally:
        db(demo_seed.reset)
        db(lambda conn: clean_world(conn, w))


async def demo_state(conn) -> dict:
    vans = await conn.fetch(
        "select id, plate_number, capacity, status, assigned_driver_id from public.vehicles "
        "where plate_number like 'demo-%' order by plate_number"
    )
    crew = await conn.fetch(
        "select id from public.crew_members where name like 'demo-%' order by id"
    )
    pickups = await conn.fetch(
        """
        select p.id, p.crew_member_id, p.report_time, p.status, p.request_type, z.label
        from public.pickup_requests p
        left join lateral (
            select label from public.pickup_zones
            order by extensions.st_distance(location, p.pickup_location) limit 1
        ) z on true
        where p.id = any($1) order by p.id
        """,
        demo_seed.fixed_rows().pickups,
    )
    return {"vans": vans, "crew": crew, "pickups": pickups}


def test_seed_creates_the_demo_morning(world):
    summary = db(lambda conn: demo_seed.seed(conn, DAY))
    state = db(demo_state)

    # The bystander van is available and has driver@'s active route: both
    # reported, neither changed.
    assert any(f"test-{RUN}" in w for w in summary["warnings"])
    assert any(w.startswith(demo_seed.DRIVER_EMAIL) for w in summary["warnings"])

    assert [v["plate_number"] for v in state["vans"]] == demo_seed.VANS
    assert {v["capacity"] for v in state["vans"]} == {14}
    assert {v["status"] for v in state["vans"]} == {"available"}
    assert [v["assigned_driver_id"] for v in state["vans"]] == [world.driver, None, None]

    assert len(state["crew"]) == 13
    pickups = state["pickups"]
    assert len(pickups) == 14
    assert {p["status"] for p in pickups} == {"pending"}
    assert [p["crew_member_id"] for p in pickups].count(world.crew_member) == 1
    zones = {p["label"] for p in pickups}
    assert len(zones) == 7 and "Westlands, Nairobi" in zones
    first = datetime.combine(DAY, datetime.min.time(), EAT) + timedelta(hours=5)
    times = [p["report_time"] for p in pickups]
    assert min(times) == first
    assert max(times) == first + timedelta(hours=2, minutes=30)


def test_seed_twice_gives_the_same_rows(world):
    # The second seed deletes and inserts the same rows: equal but for when
    # they were created.
    db(lambda conn: demo_seed.seed(conn, DAY))
    once = db(lambda conn: snapshot(conn, without="created_at"))
    db(lambda conn: demo_seed.seed(conn, DAY))
    assert db(lambda conn: snapshot(conn, without="created_at")) == once


def test_seed_and_a_played_demo_then_reset_leave_the_database_as_it_was(world):
    before = db(snapshot)
    db(lambda conn: demo_seed.seed(conn, DAY))

    async def play(conn):
        """What the demo writes: a plan, a confirmed pickup, a trip record, a
        breakdown re-plan with a notice, an acknowledgement and a message."""
        rows = demo_seed.fixed_rows()
        first = await plan(conn, rows.vans, rows.pickups)
        node, van = await conn.fetchrow(
            "select n.id, r.vehicle_id from public.route_nodes n "
            "join public.routes r on r.id = n.route_id "
            "where r.optimization_job_id = $1 order by n.seq_order limit 1",
            first,
        )
        await conn.execute(
            "insert into public.pickup_events (route_node_id, driver_id, event_type, "
            "confirmed_at, idempotency_key) values ($1, $2, 'pickup_confirmed', now(), $3)",
            node,
            world.driver,
            f"test-{RUN}-event",
        )
        await conn.execute(
            "insert into public.trip_records (route_node_id, vehicle_id, crew_count, "
            "pickup_timestamp, scheduled_report_time, actual_arrival, actual_duration_sec, "
            "day_of_week, route_corridor) values ($1, $2, 1, now(), now(), now(), 1800, 1, 'x')",
            node,
            van,
        )
        await conn.execute(
            "update public.route_nodes set superseded_at = now() where route_id in "
            "(select id from public.routes where optimization_job_id = $1)",
            first,
        )
        await conn.execute(
            "update public.routes set status = 'superseded' where optimization_job_id = $1", first
        )
        await conn.execute("update public.vehicles set status = 'broken_down' where id = $1", van)
        crew_pickup = rows.pickups[-1]
        await plan(conn, rows.vans[1:], rows.pickups[1:], trigger="vehicle_breakdown")
        await conn.execute(
            "insert into public.schedule_change_notices (pickup_request_id, reason, "
            "previous_pickup_time, new_pickup_time, acknowledged_at) "
            "values ($1, 'vehicle_breakdown', now(), now(), now())",
            crew_pickup,
        )
        await conn.execute(
            "insert into public.crew_messages (crew_member_id, preset_message_id, idempotency_key) "
            "select $1, id, $2 from public.preset_messages where code = 'running_late'",
            rows.crew[0],
            f"test-{RUN}-message",
        )

    db(play)
    deleted = db(demo_seed.reset)
    assert deleted["optimization_jobs"] == 2
    assert deleted["pickup_events"] == 1 and deleted["trip_records"] == 1
    assert deleted["schedule_change_notices"] == 1 and deleted["crew_messages"] == 1
    assert deleted["pickup_requests"] == 14 and deleted["vehicles"] == 3
    assert db(snapshot) == before


def test_reset_without_demo_rows_changes_nothing(world):
    before = db(snapshot)
    deleted = db(demo_seed.reset)
    assert not any(deleted.values())
    assert db(snapshot) == before


def test_reset_stops_on_a_job_that_mixed_demo_and_non_demo_rows(world):
    db(lambda conn: demo_seed.seed(conn, DAY))
    rows = demo_seed.fixed_rows()
    mixed = db(lambda conn: plan(conn, [rows.vans[0], world.van], rows.pickups[:2]))
    before = db(snapshot)
    try:
        with pytest.raises(MixedDemoData, match=str(mixed)):
            db(demo_seed.reset)
        assert db(snapshot) == before
    finally:

        async def unplan(conn):
            await conn.execute(
                "delete from public.route_nodes where route_id in "
                "(select id from public.routes where optimization_job_id = $1)",
                mixed,
            )
            await conn.execute(
                "delete from public.optimization_job_pickups where optimization_job_id = $1",
                mixed,
            )
            await conn.execute("delete from public.routes where optimization_job_id = $1", mixed)
            await conn.execute("delete from public.optimization_jobs where id = $1", mixed)

        db(unplan)


def test_seed_stops_without_the_test_accounts():
    async def run(conn):
        # Inside a transaction rolled back after, so the accounts look absent
        # even if another test left them.
        tr = conn.transaction()
        await tr.start()
        try:
            await conn.execute(
                "update auth.users set email = null where email = any($1)",
                [demo_seed.DRIVER_EMAIL, demo_seed.CREW_EMAIL],
            )
            with pytest.raises(SystemExit, match="seed_test_accounts"):
                await demo_seed.seed(conn, DAY)
        finally:
            await tr.rollback()

    db(run)
