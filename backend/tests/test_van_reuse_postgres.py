"""Van reuse across waves against Postgres with the migrations.

A job's wave is the span of its pickups' report times. A ticked van keeps
its routes that reach JKIA before the wave and joins the job at JKIA, free
REUSE_TURNAROUND after the latest is due in; a van with a route leaving
after the wave keeps it and is left out of the job, and the job result
lists it; a route that overlaps the wave is replaced as before. The driver's
current route is the next unfinished one.

The day is two days ahead, in Nairobi time, so every route is still to
leave. The routes these tests build by hand have fixed times; the first
test plans both waves through the API, as the dispatcher does.

They insert auth.users rows, so they run only on a throwaway database (CI's
PostGIS service), never against a Supabase host.
"""

import asyncio
import os
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import urlsplit
from uuid import uuid4

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.jobs.store import REUSE_TURNAROUND
from app.main import app
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

KEY = SigningKey("van-reuse-key")
RUN = uuid4().hex[:8]
EAT = timezone(timedelta(hours=3))
DAY: date = (datetime.now(EAT) + timedelta(days=2)).date()
SEATS = 3
WESTLANDS = "SRID=4326;POINT(36.8120 -1.2675)"
KILIMANI = "SRID=4326;POINT(36.7778 -1.2789)"


def at(hour: int, minute: int = 0) -> datetime:
    return datetime.combine(DAY, time(hour, minute), EAT)


def db(query):
    async def run():
        conn = await asyncpg.connect(DATABASE_URL, statement_cache_size=0)
        try:
            return await query(conn)
        finally:
            await conn.close()

    return asyncio.run(run())


class World:
    """Ids made by one test, all deleted afterwards."""

    def __init__(self) -> None:
        self.users: list = []
        self.crew: list = []
        self.pickups: list = []
        self.vans: dict[str, object] = {}

    def driver(self) -> object:
        user = uuid4()

        async def make(conn):
            async with conn.transaction():
                await conn.execute("insert into auth.users (id) values ($1)", user)
                await conn.execute(
                    "insert into public.profiles (id, role, full_name) values ($1, 'driver', $2)",
                    user,
                    f"test-{RUN} driver",
                )

        db(make)
        self.users.append(user)
        return user

    def van(self, name: str, driver=None) -> object:
        self.vans[name] = db(
            lambda conn: conn.fetchval(
                "insert into public.vehicles (plate_number, capacity, assigned_driver_id) "
                "values ($1, $2, $3) returning id",
                f"T{RUN}{name}",
                SEATS,
                driver,
            )
        )
        return self.vans[name]

    def pickup(self, report_time: datetime, place: str = WESTLANDS) -> object:
        async def make(conn):
            async with conn.transaction():
                crew = await conn.fetchval(
                    "insert into public.crew_members (name, role, home_location) "
                    "values ($1, 'cabin_crew', $2) returning id",
                    f"test-{RUN} crew {len(self.crew)}",
                    place,
                )
                pickup = await conn.fetchval(
                    "insert into public.pickup_requests "
                    "(crew_member_id, pickup_location, report_time, request_type) "
                    "values ($1, $2, $3, 'rostered') returning id",
                    crew,
                    place,
                    report_time,
                )
                return crew, pickup

        crew, pickup = db(make)
        self.crew.append(crew)
        self.pickups.append(pickup)
        return pickup

    def route(self, van, pickups, departure: datetime, arrival: datetime) -> object:
        """An active route made by hand, with fixed times: its pickups are
        assigned, one stop every 10 minutes from departure."""

        async def make(conn):
            async with conn.transaction():
                job = await conn.fetchval(
                    "insert into public.optimization_jobs "
                    "(trigger_type, status, idempotency_key, request_hash) "
                    "values ('scheduled', 'completed', $1, 'hash') returning id",
                    f"test-{RUN}-manual-{uuid4().hex}",
                )
                route = await conn.fetchval(
                    "insert into public.routes (vehicle_id, optimization_job_id, "
                    "total_distance_km, planned_departure, planned_arrival) "
                    "values ($1, $2, 10, $3, $4) returning id",
                    van,
                    job,
                    departure,
                    arrival,
                )
                for seq, pickup in enumerate(pickups, start=1):
                    await conn.execute(
                        "insert into public.route_nodes "
                        "(route_id, pickup_request_id, seq_order, estimated_arrival) "
                        "values ($1, $2, $3, $4)",
                        route,
                        pickup,
                        seq,
                        departure + timedelta(minutes=10 * seq),
                    )
                await conn.execute(
                    "update public.pickup_requests set status = 'assigned' where id = any($1)",
                    pickups,
                )
                return route

        return db(make)

    def clean(self) -> None:
        async def clean(conn):
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
                for table, column, ids in [
                    ("optimization_job_left_out_vehicles", "optimization_job_id", jobs),
                    ("optimization_job_pickups", "optimization_job_id", jobs),
                    ("schedule_change_notices", "pickup_request_id", self.pickups),
                    ("route_nodes", "route_id", routes),
                    ("routes", "id", routes),
                    ("optimization_jobs", "id", jobs),
                    ("pickup_requests", "id", self.pickups),
                    ("crew_members", "id", self.crew),
                    ("vehicles", "id", list(self.vans.values())),
                    ("profiles", "id", self.users),
                ]:
                    await conn.execute(f"delete from public.{table} where {column} = any($1)", ids)
                await conn.execute("delete from auth.users where id = any($1)", self.users)

        db(clean)


@pytest.fixture
def world():
    made = World()
    yield made
    made.clean()


@pytest.fixture
def client(monkeypatch, world):
    # Depends on world so the app shuts down before world's cleanup runs.
    monkeypatch.setattr(settings, "database_url", DATABASE_URL)
    monkeypatch.setattr(settings, "travel_model", "haversine")
    monkeypatch.setattr(settings, "solve_time_limit_sec", 1.0)
    monkeypatch.setattr(settings, "solver_pool_size", 1)
    monkeypatch.setattr(app.state, "jwt_keys", FakeJwks(KEY).source(), raising=False)
    monkeypatch.setattr(app.state, "jwt_issuer", ISSUER, raising=False)
    dispatcher = uuid4()

    async def make(conn):
        async with conn.transaction():
            await conn.execute("insert into auth.users (id) values ($1)", dispatcher)
            await conn.execute(
                "insert into public.profiles (id, role, full_name) values ($1, 'dispatcher', $2)",
                dispatcher,
                f"test-{RUN} dispatcher",
            )

    db(make)
    world.users.append(dispatcher)
    with TestClient(app, headers=bearer(KEY.token(dispatcher))) as client:
        yield client


def run_job(client, pickups, vans) -> dict:
    accepted = client.post(
        "/optimisation-jobs",
        json={
            "trigger_type": "scheduled",
            "pickup_request_ids": [str(p) for p in pickups],
            "vehicle_ids": [str(v) for v in vans],
        },
        headers={"Idempotency-Key": f"test-{RUN}-{uuid4().hex}"},
    )
    assert accepted.status_code == 202, accepted.text
    result = wait_for_job(client, accepted.json()["id"])
    assert result["status"] == "completed", result["error"]
    return result


def live_routes(van) -> list:
    """The van's active routes with live nodes, by departure."""
    return db(
        lambda conn: conn.fetch(
            """
            select r.id, r.planned_departure, r.planned_arrival,
                array_agg(n.pickup_request_id order by n.seq_order) as pickups
            from public.routes r
            join public.route_nodes n on n.route_id = r.id and n.superseded_at is null
            where r.vehicle_id = $1 and r.status = 'active'
            group by r.id
            order by r.planned_departure
            """,
            van,
        )
    )


def ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_a_van_is_reused_across_two_waves(client, world):
    van = world.van("A")
    early = [world.pickup(at(5, 0)), world.pickup(at(5, 15), KILIMANI)]
    mid = [world.pickup(at(10, 0)), world.pickup(at(10, 15), KILIMANI)]

    first = run_job(client, early, [van])
    second = run_job(client, mid, [van])

    assert first["unassigned"] == second["unassigned"] == []
    assert second["left_out"] == []
    # The early route stays, and the van has a second route for the mid wave.
    early_route, mid_route = live_routes(van)
    assert sorted(early_route["pickups"]) == sorted(early)
    assert sorted(mid_route["pickups"]) == sorted(mid)
    # It leaves JKIA no sooner than the turnaround after the early route.
    assert mid_route["planned_departure"] >= early_route["planned_arrival"] + REUSE_TURNAROUND
    [planned] = second["routes"]
    assert ts(planned["planned_departure"]) == mid_route["planned_departure"]


def test_a_route_that_overlaps_the_wave_is_still_replaced(client, world):
    van = world.van("A")
    # Already on the van: a route in at 10:30, after the wave starts at
    # 10:00, so it overlaps and is re-planned with the job.
    on_the_van = world.pickup(at(10, 20))
    overlapping = world.route(van, [on_the_van], at(9, 0), at(10, 30))
    wave = [world.pickup(at(10, 0)), world.pickup(at(10, 15), KILIMANI)]

    result = run_job(client, wave, [van])

    planned = {n["pickup_request_id"] for r in result["routes"] for n in r["nodes"]}
    assert planned | set(result["unassigned"]) == {str(p) for p in [*wave, on_the_van]}
    [route] = live_routes(van)
    assert route["id"] != overlapping
    status = db(
        lambda conn: conn.fetchval("select status from public.routes where id = $1", overlapping)
    )
    assert status == "superseded"


def test_a_van_with_a_later_route_is_left_out_and_listed(client, world):
    reused, busy_later = world.van("A"), world.van("B")
    later_pickup = world.pickup(at(15, 30))
    later = world.route(busy_later, [later_pickup], at(14, 30), at(15, 20))
    wave = [world.pickup(at(10, 0)), world.pickup(at(10, 15), KILIMANI)]

    result = run_job(client, wave, [reused, busy_later])

    [left_out] = result["left_out"]
    assert left_out["vehicle_id"] == str(busy_later)
    assert left_out["plate_number"] == f"T{RUN}B"
    assert left_out["reason"] == "later_route"
    assert (ts(left_out["route_departure"]), ts(left_out["route_arrival"])) == (
        at(14, 30),
        at(15, 20),
    )
    assert {r["vehicle_id"] for r in result["routes"]} == {str(reused)}
    # The later route is untouched.
    [kept] = live_routes(busy_later)
    assert (kept["id"], kept["pickups"]) == (later, [later_pickup])


def test_the_drivers_current_route_moves_on_once_route_1_is_done(client, world):
    driver = world.driver()
    van = world.van("A", driver)
    first, second = world.pickup(at(5, 0)), world.pickup(at(10, 0))
    route_1 = world.route(van, [first], at(4, 0), at(4, 50))
    route_2 = world.route(van, [second], at(9, 0), at(9, 50))
    headers = bearer(KEY.token(driver))

    def current() -> str:
        response = client.get("/drivers/me/route", headers=headers)
        assert response.status_code == 200, response.text
        return response.json()["route"]["route_id"]

    assert current() == str(route_1)
    db(
        lambda conn: conn.execute(
            "update public.pickup_requests set status = 'picked_up' where id = $1", first
        )
    )
    assert current() == str(route_2)
    # Once both are done, the latest one stays on screen.
    db(
        lambda conn: conn.execute(
            "update public.pickup_requests set status = 'picked_up' where id = $1", second
        )
    )
    assert current() == str(route_2)
