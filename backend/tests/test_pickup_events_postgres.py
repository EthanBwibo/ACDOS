"""Pickup-event upload (#33) against Postgres with the migrations.

They insert auth.users rows, so they run only on a throwaway database: when
DATABASE_URL is set in the environment (CI's PostGIS service), never against
a Supabase host. Through the HTTP API with tokens signed by a test key.

Each test seeds its own world (fresh ids, deleted afterwards by id):
drivers A and B with vans VA and VB, and pickups with nodes on
- rA, A's active route (n1..n6), with pickup 5 cancelled;
- rB, B's active route (nB);
- rDone, A's completed route (nDone).
"""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import uuid4

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app import events, reads
from app.config import settings
from app.main import app
from app.models.schemas import PickupEventIn
from tests.jwt_keys import ISSUER, FakeJwks, SigningKey, bearer

DATABASE_URL = os.environ.get("DATABASE_URL")
pytestmark = [
    pytest.mark.skipif(not DATABASE_URL, reason="needs DATABASE_URL in the environment"),
    pytest.mark.skipif(
        bool(DATABASE_URL) and "supabase" in (urlsplit(DATABASE_URL).hostname or ""),
        reason="inserts auth.users rows: never against Supabase",
    ),
]

KEY = SigningKey("events-key")
POINT = "SRID=4326;POINT(36.812 -1.2675)"


def db(query):
    async def run():
        conn = await asyncpg.connect(DATABASE_URL, statement_cache_size=0)
        try:
            return await query(conn)
        finally:
            await conn.close()

    return asyncio.run(run())


class World:
    """Ids of everything seeded, and helpers to read it back."""

    def __init__(self) -> None:
        self.now = datetime.now(UTC)
        self.users = {"A": uuid4(), "B": uuid4(), "D": uuid4()}
        self.rows: dict[str, list] = {
            k: [] for k in ["crew", "pickups", "vehicles", "jobs", "routes", "nodes"]
        }
        self.nodes: dict[str, object] = {}
        self.pickups: dict[str, object] = {}

    def event(self, node: str, key: str | None = None, driver: str = "A", **fields) -> dict:
        return {
            "idempotency_key": key or f"key-{uuid4().hex}",
            "route_node_id": str(self.nodes[node]),
            "driver_id": str(self.users[driver]),
            "event_type": "pickup_confirmed",
            "occurred_at": (self.now - timedelta(minutes=5)).isoformat(),
        } | fields

    def status(self, pickup: str) -> str:
        async def read(conn):
            return await conn.fetchval(
                "select status from public.pickup_requests where id = $1", self.pickups[pickup]
            )

        return db(read)

    def stored(self, key: str):
        async def read(conn):
            return await conn.fetchrow(
                "select confirmed_at, synced_at from public.pickup_events "
                "where idempotency_key = $1",
                key,
            )

        return db(read)


async def seed(conn, w: World) -> None:
    async with conn.transaction():
        for name, uid in w.users.items():
            await conn.execute("insert into auth.users (id) values ($1)", uid)
            role = "dispatcher" if name == "D" else "driver"
            await conn.execute(
                "insert into public.profiles (id, role, full_name) values ($1, $2, $3)",
                uid,
                role,
                f"test {name}",
            )
        vans = {}
        for name in ["A", "B"]:
            vans[name] = await conn.fetchval(
                "insert into public.vehicles (assigned_driver_id, plate_number, capacity) "
                "values ($1, $2, 14) returning id",
                w.users[name],
                f"EV {uuid4().hex[:8]}",
            )
            w.rows["vehicles"].append(vans[name])
        job = await conn.fetchval(
            "insert into public.optimization_jobs (trigger_type, status) "
            "values ('scheduled', 'completed') returning id"
        )
        w.rows["jobs"].append(job)

        async def pickup(name: str, status: str = "assigned"):
            crew = await conn.fetchval(
                "insert into public.crew_members (name, role, home_location) "
                "values ($1, 'cabin_crew', $2) returning id",
                f"events crew {name}",
                POINT,
            )
            w.rows["crew"].append(crew)
            pid = await conn.fetchval(
                "insert into public.pickup_requests "
                "(crew_member_id, pickup_location, report_time, request_type, status) "
                "values ($1, $2, $3, 'rostered', $4) returning id",
                crew,
                POINT,
                w.now + timedelta(hours=3),
                status,
            )
            w.rows["pickups"].append(pid)
            w.pickups[name] = pid
            return pid

        async def route(van, status: str, stops: list[tuple[str, str]]):
            rid = await conn.fetchval(
                "insert into public.routes "
                "(vehicle_id, optimization_job_id, total_distance_km, status, "
                "planned_departure, planned_arrival) "
                "values ($1, $2, 20, $3, now(), now() + interval '2 hours') returning id",
                van,
                job,
                status,
            )
            w.rows["routes"].append(rid)
            for seq, (node, pickup_name) in enumerate(stops, start=1):
                nid = await conn.fetchval(
                    "insert into public.route_nodes (route_id, pickup_request_id, seq_order, "
                    "estimated_arrival) values ($1, $2, $3, $4) returning id",
                    rid,
                    w.pickups[pickup_name],
                    seq,
                    w.now + timedelta(hours=1, minutes=seq),
                )
                w.rows["nodes"].append(nid)
                w.nodes[node] = nid
            return rid

        for k in range(1, 7):
            await pickup(f"p{k}", "cancelled" if k == 5 else "assigned")
        await pickup("pB")
        await pickup("pDone", "picked_up")
        w.routes = {
            "A": await route(vans["A"], "active", [(f"n{k}", f"p{k}") for k in range(1, 7)]),
            "B": await route(vans["B"], "active", [("nB", "pB")]),
            "Done": await route(vans["A"], "completed", [("nDone", "pDone")]),
        }
        w.vans = vans
        w.job = job


async def clean(conn, w: World) -> None:
    async with conn.transaction():
        await conn.execute(
            "delete from public.pickup_events where route_node_id = any($1)", w.rows["nodes"]
        )
        await conn.execute("delete from public.route_nodes where id = any($1)", w.rows["nodes"])
        await conn.execute("delete from public.routes where id = any($1)", w.rows["routes"])
        await conn.execute(
            "delete from public.optimization_jobs where id = any($1)", w.rows["jobs"]
        )
        await conn.execute(
            "delete from public.pickup_requests where id = any($1)", w.rows["pickups"]
        )
        await conn.execute("delete from public.crew_members where id = any($1)", w.rows["crew"])
        await conn.execute("delete from public.vehicles where id = any($1)", w.rows["vehicles"])
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
    monkeypatch.setattr(settings, "solver_pool_size", 1)
    monkeypatch.setattr(app.state, "jwt_keys", FakeJwks(KEY).source(), raising=False)
    monkeypatch.setattr(app.state, "jwt_issuer", ISSUER, raising=False)
    with TestClient(app) as client:
        yield client


def upload(client, world: World, events_: list[dict], as_user: str = "A") -> list[dict]:
    response = client.post(
        "/drivers/me/pickup-events",
        json={"events": events_},
        headers=bearer(KEY.token(world.users[as_user])),
    )
    assert response.status_code == 200, response.text
    return response.json()["results"]


def outcomes(results: list[dict]) -> list:
    return [(r["status"], r.get("code")) for r in results]


def test_an_upload_is_stored_and_a_resend_is_all_duplicates(client, world):
    batch = [world.event("n1"), world.event("n2", event_type="exception", exception_type="no_show")]

    first = upload(client, world, batch)
    again = upload(client, world, batch)

    assert outcomes(first) == [("accepted", None), ("accepted", None)]
    assert outcomes(again) == [("duplicate", None), ("duplicate", None)]
    assert [r["idempotency_key"] for r in first] == [e["idempotency_key"] for e in batch]
    stored = world.stored(batch[0]["idempotency_key"])
    assert stored["confirmed_at"] == datetime.fromisoformat(batch[0]["occurred_at"])
    assert stored["synced_at"] >= world.now  # server time, not device time
    assert "stop_replanned" not in first[0]
    # The server's id: on acceptance, and the same stored id on every resend.
    ids = [r["event_id"] for r in first]
    assert all(ids) and len(set(ids)) == 2
    assert [r["event_id"] for r in again] == ids


def test_one_bad_event_rejects_only_itself(client, world):
    future = (world.now + timedelta(minutes=30)).isoformat()
    batch = [
        world.event("n1"),
        world.event("n2", driver="B"),  # driver_id is not the caller
        world.event("nB"),  # driver B's stop
        world.event("n3", event_type="exception"),  # no exception_type
        world.event("n4", exception_type="no_show"),  # exception_type on a confirmation
        world.event("n6", occurred_at=future),
        world.event("n2", event_type="exception", exception_type="vehicle_issue"),
    ]

    results = upload(client, world, batch)

    assert outcomes(results) == [
        ("accepted", None),
        ("rejected", "driver_mismatch"),
        ("rejected", "not_your_stop"),
        ("rejected", "validation_failed"),
        ("rejected", "validation_failed"),
        ("rejected", "validation_failed"),
        ("accepted", None),
    ]
    assert all(r["detail"] for r in results if r["status"] == "rejected")


def test_keys_are_idempotent_within_and_across_batches(client, world):
    first = world.event("n1", key="k-same")
    changed = world.event("n2", key="k-same")

    within = upload(client, world, [first, dict(first), changed])
    later = upload(client, world, [changed])

    assert outcomes(within) == [
        ("accepted", None),
        ("duplicate", None),
        ("rejected", "idempotency_key_reused"),
    ]
    assert within[1]["event_id"] == within[0]["event_id"]
    assert "event_id" not in within[2]  # only accepted and duplicate carry one
    assert outcomes(later) == [("rejected", "idempotency_key_reused")]


def test_another_drivers_key_is_reused_not_revealed(client, world):
    upload(client, world, [world.event("nB", key="k-b", driver="B")], as_user="B")
    results = upload(client, world, [world.event("n1", key="k-b")])
    assert outcomes(results) == [("rejected", "idempotency_key_reused")]


def test_a_stop_is_confirmed_once(client, world):
    results = upload(client, world, [world.event("n3"), world.event("n3")])
    assert outcomes(results) == [("accepted", None), ("rejected", "already_confirmed")]


def test_events_move_the_pickup_status_with_guards(client, world):
    no_show = {"event_type": "exception", "exception_type": "no_show"}
    upload(
        client,
        world,
        [
            world.event("n1", **no_show),  # assigned -> missed
            world.event("n1"),  # missed -> picked_up: in request order
            world.event("n2", event_type="exception", exception_type="traffic_delay"),
            world.event("n3"),  # assigned -> picked_up
            world.event("n3", **no_show),  # picked_up never goes back
            world.event("n5"),  # cancelled is never changed
            world.event("n6", **no_show),  # assigned -> missed, and stays there
        ],
    )
    assert [world.status(p) for p in ["p1", "p2", "p3", "p5", "p6"]] == [
        "picked_up",
        "assigned",
        "picked_up",
        "cancelled",
        "missed",
    ]


def test_an_offline_pickup_synced_after_a_replan_is_accepted_and_flagged(client, world):
    confirmed_offline = world.now - timedelta(minutes=10)

    # The re-plan: n4 is superseded and its pickup moves to driver B's route.
    async def replan(conn):
        async with conn.transaction():
            await conn.execute(
                "update public.route_nodes set superseded_at = $2 where id = $1",
                world.nodes["n4"],
                world.now - timedelta(minutes=5),
            )
            world.rows["nodes"].append(
                await conn.fetchval(
                    "insert into public.route_nodes (route_id, pickup_request_id, seq_order, "
                    "estimated_arrival) values ($1, $2, 9, $3) returning id",
                    world.routes["B"],
                    world.pickups["p4"],
                    world.now + timedelta(hours=1),
                )
            )

    db(replan)
    before = world.event("n4", occurred_at=confirmed_offline.isoformat())
    after = world.event("n4", occurred_at=(world.now - timedelta(minutes=1)).isoformat())

    results = upload(client, world, [before, after])

    assert results[0] == {
        "idempotency_key": before["idempotency_key"],
        "status": "accepted",
        "event_id": results[0]["event_id"],
        "stop_replanned": True,
    }
    assert outcomes(results)[1] == ("rejected", "not_your_stop")
    assert world.status("p4") == "picked_up"


def test_a_last_stop_syncing_after_its_route_completed_is_accepted(client, world):
    results = upload(client, world, [world.event("nDone")])
    assert outcomes(results) == [("accepted", None)]


def test_only_drivers_may_upload(client, world):
    response = client.post(
        "/drivers/me/pickup-events",
        json={"events": [world.event("n1", driver="D")]},
        headers=bearer(KEY.token(world.users["D"])),
    )
    assert (response.status_code, response.json()["code"]) == (403, "forbidden")


def test_a_concurrent_upload_of_the_same_key_is_a_duplicate_not_an_error(world):
    # Another request stores the key between this one's lookup and its insert:
    # the insert waits on the key's unique index, then fails; the result must
    # be duplicate, never a 500. An exception, so only the key's index can
    # collide (a confirmation would also hit one-confirmation-per-node).
    event = PickupEventIn.model_validate(
        world.event("n1", key="k-race", event_type="exception", exception_type="no_show")
    )

    async def run():
        pool = await asyncpg.create_pool(
            DATABASE_URL, statement_cache_size=0, min_size=1, max_size=2
        )
        other = await asyncpg.connect(DATABASE_URL, statement_cache_size=0)
        try:
            tx = other.transaction()
            await tx.start()
            await other.execute(
                "insert into public.pickup_events (route_node_id, driver_id, event_type, "
                "exception_type, confirmed_at, synced_at, idempotency_key) "
                "values ($1, $2, 'exception', 'no_show', $3, now(), 'k-race')",
                event.route_node_id,
                event.driver_id,
                event.occurred_at,
            )
            racing = asyncio.create_task(events.record(pool, world.users["A"], [event], world.now))
            await asyncio.sleep(1.0)  # it looks the key up (not yet visible), then waits
            await tx.commit()
            return await racing
        finally:
            await other.close()
            await pool.close()

    [result] = asyncio.run(run())
    assert (result.status, result.code) == ("duplicate", None)


def test_two_concurrent_confirmations_of_a_stop_store_exactly_one(world):
    # Two uploads (different keys) confirm the same stop at once: one is
    # accepted, the other waits on the one-confirmation index, then is
    # rejected already_confirmed, by the index's name, never a 500. Through
    # events.record, the route's own code below auth, on two connections.
    first, second = (
        PickupEventIn.model_validate(world.event("n2", key=key)) for key in ("k-c1", "k-c2")
    )

    async def run():
        pool = await asyncpg.create_pool(
            DATABASE_URL, statement_cache_size=0, min_size=2, max_size=2
        )
        try:
            return await asyncio.gather(
                events.record(pool, world.users["A"], [first], world.now),
                events.record(pool, world.users["A"], [second], world.now),
            )
        finally:
            await pool.close()

    [[a], [b]] = asyncio.run(run())
    assert sorted([(a.status, a.code), (b.status, b.code)]) == [
        ("accepted", None),
        ("rejected", "already_confirmed"),
    ]

    async def count(conn):
        return await conn.fetchval(
            "select count(*) from public.pickup_events where route_node_id = $1",
            world.nodes["n2"],
        )

    assert db(count) == 1


# Each part of 022 and 023 is needed: with it undone, inside a rolled-back
# transaction, the same insert as driver A comes out differently.


def as_driver_after(change_sql: str, world: World, node: str, occurred_at: datetime):
    """Change the schema, then try the insert as driver A; True if allowed.
    Returns (allowed, status of the node's pickup after)."""

    async def run(conn):
        tx = conn.transaction()
        await tx.start()
        try:
            await conn.execute(change_sql)
            await conn.execute("savepoint attempt")
            await reads.become(conn, world.users["A"])
            try:
                await conn.execute(
                    "insert into public.pickup_events (route_node_id, driver_id, event_type, "
                    "confirmed_at, synced_at, idempotency_key) "
                    "values ($1, $2, 'pickup_confirmed', $3, now(), $4)",
                    world.nodes[node],
                    world.users["A"],
                    occurred_at,
                    f"k-{uuid4().hex}",
                )
                allowed = True
            except asyncpg.InsufficientPrivilegeError:
                await conn.execute("rollback to savepoint attempt")
                allowed = False
            await conn.execute("reset role")
            status = await conn.fetchval(
                "select p.status from public.pickup_requests p "
                "join public.route_nodes n on n.pickup_request_id = p.id where n.id = $1",
                world.nodes[node],
            )
            return allowed, status
        finally:
            await tx.rollback()

    return db(run)


POLICY_011 = """
    alter policy pickup_events_driver_insert on public.pickup_events with check (
        driver_id = (select auth.uid())
        and route_node_id in (
            select n.id from public.route_nodes n
            join public.routes r on r.id = n.route_id
            join public.vehicles v on v.id = r.vehicle_id
            where v.assigned_driver_id = (select auth.uid())
        )
    )
"""


def test_022_accepts_an_event_from_before_its_stop_was_replanned(world):
    # 011's policy reads route_nodes under the driver's own RLS, which since
    # 021 hides superseded nodes: it refused every event on a replanned stop,
    # even one that happened before the re-plan. 022 accepts that one, and
    # still refuses one from after.
    replanned_at = world.now - timedelta(minutes=30)

    async def supersede(conn):
        await conn.execute(
            "update public.route_nodes set superseded_at = $2 where id = $1",
            world.nodes["n6"],
            replanned_at,
        )

    db(supersede)
    early = replanned_at - timedelta(minutes=10)
    late = replanned_at + timedelta(minutes=10)
    assert as_driver_after("select 1", world, "n6", early)[0] is True
    assert as_driver_after("select 1", world, "n6", late)[0] is False
    assert as_driver_after(POLICY_011, world, "n6", early)[0] is False


def test_023_moves_the_status(world):
    assert as_driver_after("select 1", world, "n1", world.now)[1] == "picked_up"
    dropped = "drop trigger pickup_events_apply_to_pickup on public.pickup_events"
    assert as_driver_after(dropped, world, "n1", world.now)[1] == "assigned"
