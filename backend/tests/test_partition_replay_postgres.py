"""#34's partition run, replayed against Postgres with the migrations.

The Android half (PartitionTest.kt) drives the app's own outbox through a
seeded flaky network against a server double, and writes every delivery that
reached the server, in order, with the double's answers, to
docs/results/34-partition-test/deliveries.json. Here the same deliveries go
through the real API into the real database:

- each answer must be the one the double gave, so the Android half's loss and
  duplicate counts hold for the real server;
- afterwards every event the phone recorded is stored exactly once, except
  the second taps the server refuses (already_confirmed), and no stop has two
  confirmations.

Inserts auth.users rows, so it runs only on a throwaway database: when
DATABASE_URL is set in the environment (CI's PostGIS service), never against a
Supabase host. Its world (fresh ids) is deleted afterwards by id.
"""

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from tests.jwt_keys import ISSUER, FakeJwks, SigningKey, bearer

DATABASE_URL = os.environ.get("DATABASE_URL")
pytestmark = [
    pytest.mark.skipif(not DATABASE_URL, reason="needs DATABASE_URL in the environment"),
    pytest.mark.skipif(
        bool(DATABASE_URL) and "supabase" in (urlsplit(DATABASE_URL).hostname or ""),
        reason="inserts auth.users rows: never against Supabase",
    ),
]

RUN = json.loads(
    (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "results"
        / "34-partition-test"
        / "deliveries.json"
    ).read_text(encoding="utf-8")
)
KEY = SigningKey("partition-key")
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
    def __init__(self) -> None:
        self.driver = uuid4()
        self.nodes: dict[str, object] = {}  # the run's node names to route_nodes ids
        self.rows: dict[str, list] = {k: [] for k in ["crew", "pickups", "nodes"]}
        self.van = self.job = self.route = None


async def seed(conn, w: World) -> None:
    names = sorted({e["node"] for e in RUN["events"].values()})
    async with conn.transaction():
        await conn.execute("insert into auth.users (id) values ($1)", w.driver)
        await conn.execute(
            "insert into public.profiles (id, role, full_name) values ($1, 'driver', $2)",
            w.driver,
            "partition driver",
        )
        w.van = await conn.fetchval(
            "insert into public.vehicles (assigned_driver_id, plate_number, capacity) "
            "values ($1, $2, 14) returning id",
            w.driver,
            f"PT {uuid4().hex[:8]}",
        )
        w.job = await conn.fetchval(
            "insert into public.optimization_jobs (trigger_type, status) "
            "values ('scheduled', 'completed') returning id"
        )
        w.route = await conn.fetchval(
            "insert into public.routes (vehicle_id, optimization_job_id, total_distance_km, "
            "status, planned_departure, planned_arrival) "
            "values ($1, $2, 20, 'active', now(), now() + interval '2 hours') returning id",
            w.van,
            w.job,
        )
        for seq, name in enumerate(names, start=1):
            crew = await conn.fetchval(
                "insert into public.crew_members (name, role, home_location) "
                "values ($1, 'cabin_crew', $2) returning id",
                f"partition {name}",
                POINT,
            )
            pickup = await conn.fetchval(
                "insert into public.pickup_requests (crew_member_id, pickup_location, "
                "report_time, request_type, status) "
                "values ($1, $2, now() + interval '3 hours', 'rostered', 'assigned') returning id",
                crew,
                POINT,
            )
            node = await conn.fetchval(
                "insert into public.route_nodes (route_id, pickup_request_id, seq_order, "
                "estimated_arrival) values ($1, $2, $3, now() + interval '1 hour') returning id",
                w.route,
                pickup,
                seq,
            )
            w.rows["crew"].append(crew)
            w.rows["pickups"].append(pickup)
            w.rows["nodes"].append(node)
            w.nodes[name] = node


async def clean(conn, w: World) -> None:
    async with conn.transaction():
        nodes = w.rows["nodes"]
        await conn.execute("delete from public.pickup_events where route_node_id = any($1)", nodes)
        await conn.execute("delete from public.route_nodes where id = any($1)", nodes)
        await conn.execute("delete from public.routes where id = $1", w.route)
        await conn.execute("delete from public.optimization_jobs where id = $1", w.job)
        await conn.execute(
            "delete from public.pickup_requests where id = any($1)", w.rows["pickups"]
        )
        await conn.execute("delete from public.crew_members where id = any($1)", w.rows["crew"])
        await conn.execute("delete from public.vehicles where id = $1", w.van)
        await conn.execute("delete from public.profiles where id = $1", w.driver)
        await conn.execute("delete from auth.users where id = $1", w.driver)


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


def api_events(world: World) -> dict[str, dict]:
    """Every event as the API takes it, by key. The phone's times move to an
    hour ago, keeping their order and gaps, so none is in the future; a resend
    is always the same event, as on the phone."""
    times = {k: datetime.fromisoformat(e["occurred_at"]) for k, e in RUN["events"].items()}
    shift = datetime.now(UTC) - timedelta(hours=1) - min(times.values())
    return {
        key: {
            "idempotency_key": key,
            "route_node_id": str(world.nodes[e["node"]]),
            "driver_id": str(world.driver),
            "event_type": e["event_type"],
            **({"exception_type": e["exception_type"]} if e["exception_type"] else {}),
            "occurred_at": (times[key] + shift).isoformat(),
        }
        for key, e in RUN["events"].items()
    }


def test_the_partition_runs_deliveries_get_the_same_answers_from_postgres(client, world):
    events = api_events(world)
    headers = bearer(KEY.token(world.driver))
    accepted, refused = set(), set()

    for n, delivery in enumerate(RUN["deliveries"]):
        response = client.post(
            "/drivers/me/pickup-events",
            json={"events": [events[k] for k in delivery["keys"]]},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        got = [[r["status"].upper(), r.get("code")] for r in response.json()["results"]]
        assert got == delivery["answers"], f"delivery {n} ({delivery['fault']})"
        for key, (status, _) in zip(delivery["keys"], delivery["answers"], strict=True):
            (refused if status == "REJECTED" else accepted).add(key)

    async def stored(conn):
        return await conn.fetch(
            "select idempotency_key, route_node_id, event_type from public.pickup_events "
            "where route_node_id = any($1)",
            world.rows["nodes"],
        )

    rows = db(stored)
    keys = [r["idempotency_key"] for r in rows]
    # Every event the phone recorded is stored once, but for the refused second taps.
    assert len(keys) == len(set(keys))
    assert set(keys) == accepted == set(RUN["events"]) - refused
    assert refused.isdisjoint(accepted)
    confirmed = [r["route_node_id"] for r in rows if r["event_type"] == "pickup_confirmed"]
    assert len(confirmed) == len(set(confirmed))
