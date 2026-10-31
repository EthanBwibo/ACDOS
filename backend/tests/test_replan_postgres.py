"""Re-planning after a disruption (#113) against Postgres with the migrations.

They insert auth.users rows, so they run only on a throwaway database: when
DATABASE_URL is set in the environment (CI's PostGIS service), never against
a Supabase host. Through the HTTP API with tokens signed by a test key, the
way the dispatcher's app would re-plan; the commit-time race and the 025
trigger are driven directly.

Each test seeds its own world (fresh ids, deleted afterwards by id): a
dispatcher D, drivers A and B with vans VA and VB, a third van VC with no
driver, and ten pickups across Nairobi reporting in three hours. Routes are
seeded per test with route().
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
from app.jobs.store import PostgresJobStore, RouteConflictError
from app.jobs.worker import PlannedRoute, PlannedStop, SolveOutcome
from app.main import app
from app.models.schemas import OptimizationTriggerType
from app.solver.instances import SPEED_KMH
from app.solver.problem import Point, haversine_travel_time
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

KEY = SigningKey("replan-key")
RUN = uuid4().hex[:8]
PLACES = [
    (-1.2675, 36.8120),
    (-1.2789, 36.7778),
    (-1.2921, 36.8219),
    (-1.3100, 36.8500),
    (-1.2200, 36.8900),
    (-1.3300, 36.7600),
    (-1.2500, 36.7400),
    (-1.2600, 36.8000),
    (-1.2850, 36.8650),
    (-1.3000, 36.7900),
]
GRACE = timedelta(minutes=30)


def db(query):
    async def run():
        conn = await asyncpg.connect(DATABASE_URL, statement_cache_size=0)
        try:
            return await query(conn)
        finally:
            await conn.close()

    return asyncio.run(run())


class World:
    """Ids of everything seeded, and helpers to seed routes and read back."""

    def __init__(self) -> None:
        self.now = datetime.now(UTC)
        self.users = {name: uuid4() for name in ["D", "A", "B"]}
        self.vans: dict[str, UUID] = {}
        self.pickups: list[UUID] = []
        self.crew: list[UUID] = []
        self.job: UUID | None = None
        self.routes: list[UUID] = []
        self.nodes: dict[UUID, UUID] = {}  # pickup -> its seeded node

    def route(
        self,
        van: str,
        pickups: list[UUID],
        departs_in: timedelta,
        back_in: timedelta = timedelta(hours=2),
        status: str = "active",
    ) -> UUID:
        """An active route of van over pickups (now assigned), leaving the
        depot departs_in from now; its first stop is 20 minutes later."""

        async def seed(conn):
            async with conn.transaction():
                rid = await conn.fetchval(
                    """
                    insert into public.routes
                        (vehicle_id, optimization_job_id, total_distance_km, status,
                         planned_departure, planned_arrival)
                    values ($1, $2, 20, $3, $4, $5) returning id
                    """,
                    self.vans[van],
                    self.job,
                    status,
                    self.now + departs_in,
                    self.now + back_in,
                )
                for seq, pickup in enumerate(pickups, start=1):
                    self.nodes[pickup] = await conn.fetchval(
                        """
                        insert into public.route_nodes
                            (route_id, pickup_request_id, seq_order, estimated_arrival)
                        values ($1, $2, $3, $4) returning id
                        """,
                        rid,
                        pickup,
                        seq,
                        self.now + departs_in + timedelta(minutes=20 + 10 * seq),
                    )
                await conn.execute(
                    "update public.pickup_requests set status = 'assigned' "
                    "where id = any($1::uuid[])",
                    pickups,
                )
                return rid

        rid = db(seed)
        self.routes.append(rid)
        return rid

    def sql(self, query: str, *args):
        return db(lambda conn: conn.execute(query, *args))

    def confirm(self, pickup: UUID, driver: str, occurred: datetime) -> None:
        """A pickup_confirmed on the pickup's seeded node, written as
        postgres: the triggers run whatever wrote the event."""
        self.sql(
            """
            insert into public.pickup_events
                (route_node_id, driver_id, event_type, confirmed_at, synced_at, idempotency_key)
            values ($1, $2, 'pickup_confirmed', $3, now(), $4)
            """,
            self.nodes[pickup],
            self.users[driver],
            occurred,
            f"test-{RUN}-{uuid4().hex}",
        )

    def status(self, pickup: UUID) -> str:
        return db(
            lambda conn: conn.fetchval(
                "select status from public.pickup_requests where id = $1", pickup
            )
        )

    def live_node(self, pickup: UUID):
        """(node id, route id, job id) of the pickup's live node, or None."""
        return db(
            lambda conn: conn.fetchrow(
                """
                select n.id, n.route_id, r.optimization_job_id
                from public.route_nodes n join public.routes r on r.id = n.route_id
                where n.pickup_request_id = $1 and n.superseded_at is null
                """,
                pickup,
            )
        )

    def route_status(self, route: UUID) -> str:
        return db(
            lambda conn: conn.fetchval("select status from public.routes where id = $1", route)
        )


async def seed(conn, w: World) -> None:
    async with conn.transaction():
        for name, uid in w.users.items():
            await conn.execute("insert into auth.users (id) values ($1)", uid)
            await conn.execute(
                "insert into public.profiles (id, role, full_name) values ($1, $2, $3)",
                uid,
                "dispatcher" if name == "D" else "driver",
                f"test-{RUN} {name}",
            )
        for name, driver in [("VA", "A"), ("VB", "B"), ("VC", None)]:
            w.vans[name] = await conn.fetchval(
                "insert into public.vehicles (assigned_driver_id, plate_number, capacity) "
                "values ($1, $2, 4) returning id",
                w.users[driver] if driver else None,
                f"T{RUN}{name}",
            )
        for n, (lat, lon) in enumerate(PLACES):
            point = f"SRID=4326;POINT({lon} {lat})"
            crew = await conn.fetchval(
                "insert into public.crew_members (name, role, home_location) "
                "values ($1, 'cabin_crew', $2) returning id",
                f"test-{RUN} crew {n}",
                point,
            )
            w.crew.append(crew)
            w.pickups.append(
                await conn.fetchval(
                    "insert into public.pickup_requests "
                    "(crew_member_id, pickup_location, report_time, request_type) "
                    "values ($1, $2, $3, 'rostered') returning id",
                    crew,
                    point,
                    w.now + timedelta(hours=3),
                )
            )
        w.job = await conn.fetchval(
            "insert into public.optimization_jobs (trigger_type, status, idempotency_key) "
            "values ('scheduled', 'completed', $1) returning id",
            f"test-{RUN}-seed-{uuid4().hex}",
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
        await conn.execute(
            "delete from public.pickup_events where route_node_id in "
            "(select id from public.route_nodes where route_id = any($1))",
            routes,
        )
        await conn.execute("delete from public.route_nodes where route_id = any($1)", routes)
        await conn.execute("delete from public.routes where id = any($1)", routes)
        await conn.execute(
            "delete from public.optimization_job_pickups where optimization_job_id = any($1)",
            jobs,
        )
        await conn.execute("delete from public.optimization_jobs where id = any($1)", jobs)
        await conn.execute("delete from public.pickup_requests where id = any($1)", w.pickups)
        await conn.execute("delete from public.crew_members where id = any($1)", w.crew)
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
    monkeypatch.setattr(settings, "van_return_grace_min", GRACE.total_seconds() / 60)
    monkeypatch.setattr(app.state, "jwt_keys", FakeJwks(KEY).source(), raising=False)
    monkeypatch.setattr(app.state, "jwt_issuer", ISSUER, raising=False)
    with TestClient(app, headers=bearer(KEY.token(world.users["D"]))) as client:
        yield client


def post(client, world, pickups, vans, trigger="flight_delay", at=None):
    if at is not None:
        app.state.job_runner.now = lambda: at
    return client.post(
        "/optimisation-jobs",
        json={
            "trigger_type": trigger,
            "pickup_request_ids": [str(p) for p in pickups],
            "vehicle_ids": [str(world.vans[v]) for v in vans],
        },
        headers={"Idempotency-Key": f"test-{RUN}-{uuid4().hex}"},
    )


def replan(client, world, pickups, vans, trigger="flight_delay", at=None) -> dict:
    accepted = post(client, world, pickups, vans, trigger, at)
    assert accepted.status_code == 202, accepted.text
    result = wait_for_job(client, accepted.json()["id"])
    assert result["status"] == "completed", result["error"]
    return result


def planned(result: dict) -> set[str]:
    """Every pickup the job planned: routed or unassigned."""
    return {n["pickup_request_id"] for r in result["routes"] for n in r["nodes"]} | set(
        result["unassigned"]
    )


def test_the_job_writes_when_each_van_leaves_and_reaches_jkia(client, world):
    result = replan(client, world, world.pickups[:4], ["VA", "VB"], trigger="scheduled")
    rows = db(
        lambda conn: conn.fetch(
            "select vehicle_id, planned_departure, planned_arrival from public.routes "
            "where optimization_job_id = $1",
            UUID(result["id"]),
        )
    )
    assert len(rows) == len(result["routes"]) > 0
    stored = {r["vehicle_id"]: r for r in rows}
    depot = Point(settings.depot_lat, settings.depot_lon)
    drive = haversine_travel_time(SPEED_KMH)
    places = dict(zip(map(str, world.pickups), PLACES, strict=True))
    for route in result["routes"]:
        row = stored[UUID(route["vehicle_id"])]
        departure = datetime.fromisoformat(route["planned_departure"])
        assert departure == row["planned_departure"]
        assert datetime.fromisoformat(route["planned_arrival"]) == row["planned_arrival"]
        # The solver's start: stop 1's ETA minus the drive to it.
        first = min(route["nodes"], key=lambda n: n["seq_order"])
        to_first = drive(depot, Point(*places[first["pickup_request_id"]]), 0)
        eta = datetime.fromisoformat(first["estimated_arrival"])
        assert (eta - departure).total_seconds() == pytest.approx(to_first, abs=1)
        last = max(datetime.fromisoformat(n["estimated_arrival"]) for n in route["nodes"])
        assert row["planned_arrival"] > last


def test_a_route_has_departed_once_its_van_was_due_to_leave(client, world):
    p1, p2 = world.pickups[:2]
    # VA left 5 minutes ago and reaches its first stop in 15: before #113 the
    # first stop's ETA decided, and this route could still be replaced.
    world.route("VA", [p1], departs_in=timedelta(minutes=-5))
    world.route("VB", [p2], departs_in=timedelta(minutes=10))

    refused = post(client, world, [p1], ["VC"])
    assert refused.status_code == 409
    assert (refused.json()["code"], refused.json()["pickup_request_ids"]) == (
        "departed_routes",
        [str(p1)],
    )
    # VB is due to leave in 10 minutes: its route can still be re-planned.
    replan(client, world, [p2], ["VC"])


def test_a_replan_of_one_pickup_takes_its_whole_route(client, world):
    p1, p2, p3, p4 = world.pickups[:4]
    old = world.route("VA", [p1, p2, p3], departs_in=timedelta(hours=1))

    result = replan(client, world, [p1, p4], ["VB", "VC"])

    assert planned(result) == {str(p) for p in [p1, p2, p3, p4]}
    assert world.route_status(old) == "superseded"
    for pickup in [p1, p2, p3]:
        live = world.live_node(pickup)
        if str(pickup) in result["unassigned"]:
            assert live is None and world.status(pickup) == "pending"
        else:
            assert str(live["optimization_job_id"]) == result["id"]


@pytest.mark.parametrize("done", ["picked_up", "missed", "cancelled"])
def test_a_route_mate_past_assigned_is_dropped_without_a_new_node(client, world, done):
    p1, p2 = world.pickups[:2]
    # p2's status moved without an event on this node: collected or missed
    # on a route it had been re-planned away from, or cancelled.
    old = world.route("VA", [p1, p2], departs_in=timedelta(hours=1))
    world.sql("update public.pickup_requests set status = $2 where id = $1", p2, done)

    result = replan(client, world, [p1], ["VB"])

    assert planned(result) == {str(p1)}
    assert world.live_node(p2) is None
    assert world.status(p2) == done
    assert world.route_status(old) == "superseded"


def test_a_van_on_the_road_is_refused_until_it_is_due_back(client, world):
    p1, p2 = world.pickups[:2]
    road = world.route("VA", [p1], departs_in=timedelta(minutes=-30), back_in=timedelta(minutes=30))

    def attempt(at):
        return post(client, world, [p2], ["VA", "VB"], at=at)

    for at in [world.now, world.now + timedelta(minutes=30) + GRACE - timedelta(minutes=1)]:
        refused = attempt(at)
        assert refused.status_code == 409, at
        assert (refused.json()["code"], refused.json()["vehicle_ids"]) == (
            "vehicles_on_departed_routes",
            [str(world.vans["VA"])],
        )
    # Due back with the grace period over: free again.
    assert attempt(world.now + timedelta(minutes=30) + GRACE).status_code == 202
    # A completed route frees its van at once.
    world.sql("update public.routes set status = 'completed' where id = $1", road)
    assert attempt(world.now).status_code == 202


def test_a_van_that_left_early_is_on_the_road(client, world):
    p1, p2 = world.pickups[:2]
    world.route("VA", [p1], departs_in=timedelta(minutes=20))
    world.confirm(p1, "A", world.now - timedelta(minutes=1))

    refused = post(client, world, [p2], ["VA"])
    assert refused.json()["code"] == "vehicles_on_departed_routes"


def test_a_broken_down_van_is_refused(client, world):
    world.sql("update public.vehicles set status = 'broken_down' where id = $1", world.vans["VA"])
    refused = post(client, world, world.pickups[:1], ["VA", "VB"])
    assert refused.status_code == 422
    assert (refused.json()["code"], refused.json()["vehicle_ids"]) == (
        "not_plannable",
        [str(world.vans["VA"])],
    )


def test_a_breakdown_replan_moves_what_the_broken_van_had_not_collected(client, world):
    collected, second, third = world.pickups[:3]
    broken = world.route("VA", [collected, second, third], departs_in=timedelta(minutes=-20))
    world.confirm(collected, "A", world.now - timedelta(minutes=5))
    collected_node = world.nodes[collected]

    # Not broken down yet: its route is departed, whatever the trigger.
    for trigger in ["vehicle_breakdown", "flight_delay"]:
        refused = post(client, world, [second], ["VB"], trigger=trigger)
        assert refused.json()["code"] == "departed_routes", trigger

    world.sql("update public.vehicles set status = 'broken_down' where id = $1", world.vans["VA"])
    # Only a vehicle_breakdown re-plan frees the broken van's route.
    refused = post(client, world, [second], ["VB"], trigger="flight_delay")
    assert refused.json()["code"] == "departed_routes"

    # One requested pickup takes the route's other uncollected one with it.
    result = replan(client, world, [second], ["VB"], trigger="vehicle_breakdown")

    assert planned(result) == {str(second), str(third)}
    for pickup in [second, third]:
        live = world.live_node(pickup)
        assert str(live["optimization_job_id"]) == result["id"]
        assert world.status(pickup) == "assigned"
    # The collected one keeps its node and status, so the route stays.
    assert world.live_node(collected)["id"] == collected_node
    assert world.status(collected) == "picked_up"
    assert world.route_status(broken) == "active"


def test_the_breakdown_route_is_superseded_once_nothing_is_left_on_it(client, world):
    p1, p2 = world.pickups[:2]
    broken = world.route("VA", [p1, p2], departs_in=timedelta(minutes=-20))
    world.sql("update public.vehicles set status = 'broken_down' where id = $1", world.vans["VA"])

    replan(client, world, [p1, p2], ["VB"], trigger="vehicle_breakdown")

    assert world.route_status(broken) == "superseded"


# The 025 trigger: a confirmation on a superseded node takes the pickup off
# the route it was re-planned to. Each runs in a transaction rolled back at
# the end, so its events and changes need no cleanup.


def replanned_off_va(world: World) -> UUID:
    """p1 was on VA's route until a re-plan superseded it 10 minutes ago.
    Returns VA's node for p1; the caller puts p1 on VB's route."""
    p1 = world.pickups[0]
    old = world.route("VA", [p1], departs_in=timedelta(hours=1))
    world.sql(
        "update public.route_nodes set superseded_at = $2 where id = $1",
        world.nodes[p1],
        world.now - timedelta(minutes=10),
    )
    world.sql("update public.routes set status = 'superseded' where id = $1", old)
    return world.nodes[p1]


def run_rolled_back(world: World, steps):
    async def run(conn):
        tx = conn.transaction()
        await tx.start()
        try:
            return await steps(conn)
        finally:
            await tx.rollback()

    return db(run)


async def insert_event(conn, node, driver, occurred, event_type="pickup_confirmed"):
    await conn.execute(
        """
        insert into public.pickup_events
            (route_node_id, driver_id, event_type, exception_type, confirmed_at, synced_at,
             idempotency_key)
        values ($1, $2, $3, $4, $5, now(), $6)
        """,
        node,
        driver,
        event_type,
        "no_show" if event_type == "exception" else None,
        occurred,
        f"k-{uuid4().hex}",
    )


async def state(conn, node, route):
    """(node still live, its route's status)"""
    return (
        await conn.fetchval(
            "select superseded_at is null from public.route_nodes where id = $1", node
        ),
        await conn.fetchval("select status from public.routes where id = $1", route),
    )


@pytest.fixture
def moved(world):
    """p1 moved from VA's route to VB's (alone there) 10 minutes ago, and the
    sync to come is A's confirmation from 15 minutes ago, before the move."""
    a_node = replanned_off_va(world)
    b_route = world.route("VB", [world.pickups[0]], departs_in=timedelta(hours=1))
    return world, a_node, world.nodes[world.pickups[0]], b_route, world.now - timedelta(minutes=15)


def test_025_takes_a_stop_collected_by_another_van_off_its_route(moved):
    world, a_node, b_node, b_route, occurred = moved

    async def steps(conn):
        await insert_event(conn, a_node, world.users["A"], occurred)
        return await state(conn, b_node, b_route), await conn.fetchval(
            "select status from public.pickup_requests where id = $1", world.pickups[0]
        )

    (b_live, b_status), pickup_status = run_rolled_back(world, steps)
    assert not b_live
    # Nothing left on VB's route: superseded.
    assert b_status == "superseded"
    assert pickup_status == "picked_up"


def test_025_is_needed(moved):
    world, a_node, b_node, b_route, occurred = moved

    async def steps(conn):
        await conn.execute(
            "drop trigger pickup_events_drop_stop_collected_elsewhere on public.pickup_events"
        )
        await insert_event(conn, a_node, world.users["A"], occurred)
        return await state(conn, b_node, b_route)

    assert run_rolled_back(world, steps) == (True, "active")


def test_025_leaves_the_rest_of_the_route_running(world):
    p1, p2 = world.pickups[:2]
    a_node = replanned_off_va(world)
    b_route = world.route("VB", [p1, p2], departs_in=timedelta(hours=1))
    b_node, other = world.nodes[p1], world.nodes[p2]

    async def steps(conn):
        await insert_event(conn, a_node, world.users["A"], world.now - timedelta(minutes=15))
        return await state(conn, b_node, b_route), await state(conn, other, b_route)

    (b_live, b_status), (other_live, _) = run_rolled_back(world, steps)
    assert not b_live and other_live
    assert b_status == "active"


def test_025_keeps_a_stop_the_other_van_recorded(moved):
    world, a_node, b_node, b_route, occurred = moved

    async def steps(conn):
        # B confirmed first: a double confirmation, both kept as recorded.
        await insert_event(conn, b_node, world.users["B"], world.now - timedelta(minutes=2))
        await insert_event(conn, a_node, world.users["A"], occurred)
        return await state(conn, b_node, b_route)

    assert run_rolled_back(world, steps) == (True, "active")


def test_025_ignores_anything_but_a_confirmation(moved):
    world, a_node, b_node, b_route, occurred = moved

    async def steps(conn):
        await insert_event(conn, a_node, world.users["A"], occurred, event_type="exception")
        return await state(conn, b_node, b_route)

    assert run_rolled_back(world, steps) == (True, "active")


def test_after_025_the_other_vans_later_confirmation_is_refused(moved):
    world, a_node, b_node, _, occurred = moved

    async def steps(conn, sync_a_first: bool):
        if sync_a_first:
            await insert_event(conn, a_node, world.users["A"], occurred)
        await reads.become(conn, world.users["B"])
        try:
            # After the trigger's superseded_at (its transaction's now()).
            later = datetime.now(UTC) + timedelta(minutes=1)
            await insert_event(conn, b_node, world.users["B"], later)
        except asyncpg.InsufficientPrivilegeError:
            return False
        return True

    assert run_rolled_back(world, lambda conn: steps(conn, sync_a_first=False)) is True
    assert run_rolled_back(world, lambda conn: steps(conn, sync_a_first=True)) is False


def test_a_pickup_collected_while_the_job_ran_fails_the_commit(world):
    """The trigger takes p1 off VB's route while a job over p1 is solving:
    the commit must not give it a new node."""
    p1, p2 = world.pickups[:2]
    a_node = replanned_off_va(world)
    world.route("VB", [p1, p2], departs_in=timedelta(hours=1))

    async def run(conn):
        pool = await asyncpg.create_pool(
            DATABASE_URL, statement_cache_size=0, min_size=1, max_size=2
        )
        try:
            store = PostgresJobStore(pool, Point(settings.depot_lat, settings.depot_lon), GRACE)
            job = await store.create_job(
                f"test-{RUN}-race", "hash", OptimizationTriggerType.FLIGHT_DELAY
            )
            # What the solver returned, from before the confirmation synced.
            soon = world.now + timedelta(hours=2)
            outcome = SolveOutcome(
                (
                    PlannedRoute(
                        str(world.vans["VC"]),
                        (PlannedStop(str(p1), soon), PlannedStop(str(p2), soon)),
                        departure=soon - timedelta(minutes=20),
                        arrival=soon + timedelta(minutes=40),
                    ),
                ),
                {str(p1): 0, str(p2): 0},
                (),
            )
            await insert_event(conn, a_node, world.users["A"], world.now - timedelta(minutes=15))
            with pytest.raises(RouteConflictError) as failed:
                await store.complete(job.id, outcome, world.now, breakdown=False)
            return failed.value.conflicts
        finally:
            await pool.close()

    conflicts = db(run)
    assert conflicts.not_plannable == [p1]
    assert world.live_node(p1) is None
    assert world.status(p1) == "picked_up"
    # Nothing of the job was written: p2 is still on VB's route.
    assert world.live_node(p2)["optimization_job_id"] == world.job
