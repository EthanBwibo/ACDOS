"""Schedule-change notices (#53) against Postgres with the migrations.

They insert auth.users rows, so they run only on a throwaway database: when
DATABASE_URL is set in the environment (CI's PostGIS service), never against
a Supabase host.

Each test seeds its own world (fresh ids, deleted afterwards by id):
dispatcher D, driver A, crew accounts C and E with a pickup each (pC, pE),
vans VA and VB, and pC on an active route of VA's that leaves in an hour.
"""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app import reads
from app.config import settings
from app.jobs.store import PostgresJobStore
from app.jobs.worker import PlannedRoute, PlannedStop, SolveOutcome
from app.main import app
from app.models.schemas import OptimizationTriggerType
from app.solver.problem import Point
from tests.job_api import wait_for_job
from tests.jwt_keys import ISSUER, FakeJwks, SigningKey, bearer

DATABASE_URL = os.environ.get("DATABASE_URL")
pytestmark = [
    pytest.mark.skipif(not DATABASE_URL, reason="needs DATABASE_URL in the environment"),
    pytest.mark.skipif(
        bool(DATABASE_URL) and "supabase" in (urlsplit(DATABASE_URL).hostname or ""),
        reason="inserts auth.users rows: never against Supabase",
    ),
]

KEY = SigningKey("notices-key")
RUN = uuid4().hex[:8]
GRACE = timedelta(minutes=30)
POINTS = {"C": (-1.2675, 36.8120), "E": (-1.2921, 36.8219)}


def db(query):
    async def run():
        conn = await asyncpg.connect(DATABASE_URL, statement_cache_size=0)
        try:
            return await query(conn)
        finally:
            await conn.close()

    return asyncio.run(run())


class World:
    def __init__(self) -> None:
        self.now = datetime.now(UTC)
        self.users = {name: uuid4() for name in ["D", "A", "C", "E"]}
        self.crew: dict[str, UUID] = {}
        self.pickups: dict[str, UUID] = {}
        self.vans: dict[str, UUID] = {}
        self.job: UUID | None = None
        self.route: UUID | None = None
        self.node: UUID | None = None
        # pC's pickup time on VA's route, as crew were told.
        self.eta = self.now + timedelta(hours=1, minutes=20)

    def sql(self, query: str, *args):
        return db(lambda conn: conn.execute(query, *args))

    def notices(self, pickup: str) -> list:
        return db(
            lambda conn: conn.fetch(
                "select * from public.schedule_change_notices where pickup_request_id = $1 "
                "order by issued_at, id",
                self.pickups[pickup],
            )
        )


async def seed(conn, w: World) -> None:
    async with conn.transaction():
        roles = {"D": "dispatcher", "A": "driver", "C": "crew", "E": "crew"}
        for name, uid in w.users.items():
            await conn.execute("insert into auth.users (id) values ($1)", uid)
            await conn.execute(
                "insert into public.profiles (id, role, full_name) values ($1, $2, $3)",
                uid,
                roles[name],
                f"test-{RUN} {name}",
            )
        for name in ["C", "E"]:
            lat, lon = POINTS[name]
            point = f"SRID=4326;POINT({lon} {lat})"
            w.crew[name] = await conn.fetchval(
                "insert into public.crew_members (profile_id, name, role, home_location) "
                "values ($1, $2, 'cabin_crew', $3) returning id",
                w.users[name],
                f"test-{RUN} crew {name}",
                point,
            )
            w.pickups[name] = await conn.fetchval(
                "insert into public.pickup_requests "
                "(crew_member_id, pickup_location, report_time, request_type) "
                "values ($1, $2, $3, 'rostered') returning id",
                w.crew[name],
                point,
                w.now + timedelta(hours=3),
            )
        for name, driver in [("VA", w.users["A"]), ("VB", None)]:
            w.vans[name] = await conn.fetchval(
                "insert into public.vehicles (assigned_driver_id, plate_number, capacity) "
                "values ($1, $2, 7) returning id",
                driver,
                f"N{RUN}{name}",
            )
        w.job = await conn.fetchval(
            "insert into public.optimization_jobs (trigger_type, status, idempotency_key) "
            "values ('scheduled', 'completed', $1) returning id",
            f"test-{RUN}-seed-{uuid4().hex}",
        )
        w.route = await conn.fetchval(
            "insert into public.routes (vehicle_id, optimization_job_id, total_distance_km, "
            "planned_departure, planned_arrival) values ($1, $2, 20, $3, $4) returning id",
            w.vans["VA"],
            w.job,
            w.now + timedelta(hours=1),
            w.now + timedelta(hours=2),
        )
        w.node = await conn.fetchval(
            "insert into public.route_nodes (route_id, pickup_request_id, seq_order, "
            "estimated_arrival) values ($1, $2, 1, $3) returning id",
            w.route,
            w.pickups["C"],
            w.eta,
        )
        await conn.execute(
            "update public.pickup_requests set status = 'assigned' where id = $1", w.pickups["C"]
        )


async def clean(conn, w: World) -> None:
    async with conn.transaction():
        jobs = [
            r["id"]
            for r in await conn.fetch(
                "select id from public.optimization_jobs where idempotency_key like $1",
                f"test-{RUN}-%",
            )
        ]
        routes = [
            r["id"]
            for r in await conn.fetch(
                "select id from public.routes where optimization_job_id = any($1)", jobs
            )
        ]
        pickups = list(w.pickups.values())
        await conn.execute(
            "delete from public.schedule_change_notices where pickup_request_id = any($1)",
            pickups,
        )
        await conn.execute("delete from public.route_nodes where route_id = any($1)", routes)
        await conn.execute("delete from public.routes where id = any($1)", routes)
        await conn.execute(
            "delete from public.optimization_job_pickups where optimization_job_id = any($1)",
            jobs,
        )
        await conn.execute("delete from public.optimization_jobs where id = any($1)", jobs)
        await conn.execute("delete from public.pickup_requests where id = any($1)", pickups)
        await conn.execute(
            "delete from public.crew_members where id = any($1)", list(w.crew.values())
        )
        await conn.execute("delete from public.vehicles where id = any($1)", list(w.vans.values()))
        users = list(w.users.values())
        await conn.execute("delete from public.profiles where id = any($1)", users)
        await conn.execute("delete from auth.users where id = any($1)", users)


@pytest.fixture
def world():
    w = World()
    try:
        db(lambda conn: seed(conn, w))
        yield w
    finally:
        db(lambda conn: clean(conn, w))


@pytest.fixture
def client(monkeypatch, world):
    monkeypatch.setattr(settings, "database_url", DATABASE_URL)
    monkeypatch.setattr(settings, "travel_model", "haversine")
    monkeypatch.setattr(settings, "solve_time_limit_sec", 1.0)
    monkeypatch.setattr(settings, "solver_pool_size", 1)
    monkeypatch.setattr(app.state, "jwt_keys", FakeJwks(KEY).source(), raising=False)
    monkeypatch.setattr(app.state, "jwt_issuer", ISSUER, raising=False)
    with TestClient(app) as client:
        yield client


def as_user(world: World, name: str) -> dict:
    return bearer(KEY.token(world.users[name]))


def commit(world: World, trigger: OptimizationTriggerType, van: str | None, moved: timedelta):
    """A job over pC committed straight to the store, as the runner would:
    pC on van at its old pickup time plus moved, or unassigned (van None)."""

    async def run(conn):
        pool = await asyncpg.create_pool(DATABASE_URL, statement_cache_size=0, max_size=2)
        try:
            store = PostgresJobStore(pool, Point(-1.3192, 36.9278), GRACE)
            job = await store.create_job(f"test-{RUN}-{uuid4().hex}", "hash", trigger)
            pc = str(world.pickups["C"])
            if van is None:
                outcome = SolveOutcome((), {}, (pc,))
                vans = [world.vans["VA"]]
            else:
                stop = PlannedStop(pc, world.eta + moved)
                route = PlannedRoute(
                    str(world.vans[van]),
                    (stop,),
                    departure=stop.arrival - timedelta(minutes=20),
                    arrival=stop.arrival + timedelta(minutes=40),
                )
                outcome = SolveOutcome((route,), {pc: 0}, ())
                vans = [world.vans[van]]
            await store.complete(job.id, outcome, vans, world.now, breakdown=False)
        finally:
            await pool.close()

    db(run)


FLIGHT_DELAY = OptimizationTriggerType.FLIGHT_DELAY


@pytest.mark.parametrize(
    ("van", "moved", "notice"),
    [
        ("VA", timedelta(seconds=30), False),
        ("VA", timedelta(minutes=2), True),
        ("VA", -timedelta(minutes=2), True),
        ("VB", timedelta(0), True),
        (None, timedelta(0), True),
    ],
    ids=["same-van-30s", "same-van-2min-later", "same-van-2min-earlier", "other-van", "unassigned"],
)
def test_a_notice_when_the_pickup_time_or_van_changes(world, van, moved, notice):
    commit(world, FLIGHT_DELAY, van, moved)

    rows = world.notices("C")
    if not notice:
        assert rows == []
        return
    [row] = rows
    assert row["reason"] == "flight_delay"
    assert row["previous_pickup_time"] == world.eta
    expected = None if van is None else world.eta + moved
    assert row["new_pickup_time"] == expected
    assert row["issued_at"] == world.now
    assert (row["delivered_at"], row["acknowledged_at"]) == (None, None)


def test_a_scheduled_job_writes_no_notice(world):
    commit(world, OptimizationTriggerType.SCHEDULED, "VB", timedelta(minutes=10))
    assert world.notices("C") == []


def test_a_pickup_planned_for_the_first_time_gets_no_notice(world):
    """pE had no route: a re-plan that gives it one has nothing to change."""

    async def run(conn):
        pool = await asyncpg.create_pool(DATABASE_URL, statement_cache_size=0, max_size=2)
        try:
            store = PostgresJobStore(pool, Point(-1.3192, 36.9278), GRACE)
            job = await store.create_job(f"test-{RUN}-{uuid4().hex}", "hash", FLIGHT_DELAY)
            pe = str(world.pickups["E"])
            soon = world.now + timedelta(hours=2)
            route = PlannedRoute(
                str(world.vans["VB"]),
                (PlannedStop(pe, soon),),
                departure=soon - timedelta(minutes=20),
                arrival=soon + timedelta(minutes=40),
            )
            outcome = SolveOutcome((route,), {pe: 0}, ())
            await store.complete(job.id, outcome, [world.vans["VB"]], world.now, breakdown=False)
        finally:
            await pool.close()

    db(run)
    assert world.notices("E") == []


def test_crew_see_the_change_and_acknowledge_it(client, world):
    """A flight_delay re-plan through the API moves pC to VB; C sees the
    notice on /crew/me/pickup until they acknowledge it."""
    accepted = client.post(
        "/optimisation-jobs",
        json={
            "trigger_type": "flight_delay",
            "pickup_request_ids": [str(world.pickups["C"])],
            "vehicle_ids": [str(world.vans["VB"])],
        },
        headers=as_user(world, "D") | {"Idempotency-Key": f"test-{RUN}-{uuid4().hex}"},
    )
    assert accepted.status_code == 202, accepted.text
    result = wait_for_job(client, accepted.json()["id"])
    assert result["status"] == "completed", result["error"]
    [node] = result["routes"][0]["nodes"]

    [row] = world.notices("C")
    pickup = client.get("/crew/me/pickup", headers=as_user(world, "C")).json()["pickup"]
    assert pickup["needs_ack"] is True
    notice = pickup["notice"]
    assert notice["id"] == str(row["id"])
    assert notice["reason"] == "flight_delay"
    assert datetime.fromisoformat(notice["previous_pickup_time"]) == world.eta
    assert notice["new_pickup_time"] == node["estimated_arrival"]
    assert pickup["scheduled_pickup"] == node["estimated_arrival"]

    path = f"/crew/me/notices/{row['id']}/acknowledge"
    first = client.post(path, headers=as_user(world, "C"))
    assert first.status_code == 200, first.text
    assert first.json()["id"] == str(row["id"])
    # Safe to retry: the first time stands.
    assert client.post(path, headers=as_user(world, "C")).json() == first.json()
    [row] = world.notices("C")
    assert row["acknowledged_at"] == datetime.fromisoformat(first.json()["acknowledged_at"])

    pickup = client.get("/crew/me/pickup", headers=as_user(world, "C")).json()["pickup"]
    assert (pickup["needs_ack"], pickup["notice"]) == (False, None)


def add_notice(world: World, pickup: str, issued_in: timedelta) -> UUID:
    return db(
        lambda conn: conn.fetchval(
            "insert into public.schedule_change_notices (pickup_request_id, reason, "
            "previous_pickup_time, new_pickup_time, issued_at) "
            "values ($1, 'flight_delay', $2, $3, $4) returning id",
            world.pickups[pickup],
            world.eta,
            world.eta + timedelta(minutes=30),
            world.now + issued_in,
        )
    )


def test_the_latest_notice_is_shown_and_acknowledging_it_clears_earlier_ones(client, world):
    first = add_notice(world, "C", timedelta(minutes=-10))
    latest = add_notice(world, "C", timedelta(minutes=-5))
    pickup = client.get("/crew/me/pickup", headers=as_user(world, "C")).json()["pickup"]
    assert pickup["notice"]["id"] == str(latest)

    ack = client.post(f"/crew/me/notices/{latest}/acknowledge", headers=as_user(world, "C"))
    assert ack.status_code == 200, ack.text
    assert {r["id"]: r["acknowledged_at"] is not None for r in world.notices("C")} == {
        first: True,
        latest: True,
    }


def test_acknowledging_an_earlier_notice_leaves_a_later_one_pending(client, world):
    first = add_notice(world, "C", timedelta(minutes=-10))
    latest = add_notice(world, "C", timedelta(minutes=-5))
    client.post(f"/crew/me/notices/{first}/acknowledge", headers=as_user(world, "C"))
    pickup = client.get("/crew/me/pickup", headers=as_user(world, "C")).json()["pickup"]
    assert (pickup["needs_ack"], pickup["notice"]["id"]) == (True, str(latest))


@pytest.mark.parametrize(("user", "status"), [("E", 404), ("A", 403), ("D", 403)])
def test_only_its_crew_member_may_acknowledge_a_notice(client, world, user, status):
    notice = add_notice(world, "C", timedelta(minutes=-1))
    response = client.post(f"/crew/me/notices/{notice}/acknowledge", headers=as_user(world, user))
    assert response.status_code == status
    assert world.notices("C")[0]["acknowledged_at"] is None


# RLS (026), as each role, in a transaction rolled back at the end.


def as_role(world: World, name: str, steps):
    async def run(conn):
        tx = conn.transaction()
        await tx.start()
        try:
            await reads.become(conn, world.users[name])
            return await steps(conn)
        finally:
            await tx.rollback()

    return db(run)


def visible(conn):
    return conn.fetch("select id from public.schedule_change_notices")


def test_crew_see_only_their_own_notices_and_drivers_none(world):
    mine = add_notice(world, "C", timedelta(minutes=-1))
    theirs = add_notice(world, "E", timedelta(minutes=-1))
    ours = {mine, theirs}

    def ids(name):
        return {r["id"] for r in as_role(world, name, visible)} & ours

    assert ids("C") == {mine}
    assert ids("E") == {theirs}
    assert ids("A") == set()
    assert ids("D") == ours


def test_crew_may_set_acknowledged_at_and_nothing_else(world):
    notice = add_notice(world, "C", timedelta(minutes=-1))

    async def acknowledge(conn):
        await conn.execute(
            "update public.schedule_change_notices set acknowledged_at = now() where id = $1",
            notice,
        )
        return await conn.fetchval(
            "select acknowledged_at is not null from public.schedule_change_notices where id = $1",
            notice,
        )

    assert as_role(world, "C", acknowledge) is True

    attempts = {
        "change the reason": (
            "update public.schedule_change_notices set reason = 'vehicle_breakdown' where id = $1"
        ),
        "un-acknowledge": (
            "update public.schedule_change_notices set acknowledged_at = null where id = $1"
        ),
        "insert": (
            "insert into public.schedule_change_notices (pickup_request_id, reason, "
            "previous_pickup_time) select pickup_request_id, reason, previous_pickup_time "
            "from public.schedule_change_notices where id = $1"
        ),
        "delete": "delete from public.schedule_change_notices where id = $1",
    }
    for what, query in attempts.items():

        async def attempt(conn, query=query):
            await conn.execute(query, notice)

        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            as_role(world, "C", attempt)
        assert world.notices("C")[0]["acknowledged_at"] is None, what


def test_crew_cannot_acknowledge_another_crew_members_notice(world):
    theirs = add_notice(world, "E", timedelta(minutes=-1))

    async def acknowledge(conn):
        return await conn.execute(
            "update public.schedule_change_notices set acknowledged_at = now() where id = $1",
            theirs,
        )

    assert as_role(world, "C", acknowledge) == "UPDATE 0"
