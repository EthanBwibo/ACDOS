"""Optimisation job API (#51) against a real Postgres with the migrations.

Runs only with DATABASE_URL set: in CI, the PostGIS service the backend job
starts; locally, Supabase. Every row it makes is tagged with this run's id
and deleted afterwards, whatever the outcome.

Through the HTTP API, so what is tested is what the app does: the lifespan
connects, the runner solves in a solver process, the store writes.
"""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from tests.job_api import wait_for_job

DATABASE_URL = os.environ.get("DATABASE_URL") or settings.database_url

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="needs DATABASE_URL")

RUN = uuid4().hex[:8]
SEATS = 3
CREW = [
    (-1.2675, 36.8120),
    (-1.2789, 36.7778),
    (-1.2921, 36.8219),
    (-1.3100, 36.8500),
    (-1.2200, 36.8900),
]


def db(query):
    """Run query(conn) on a fresh connection, on its own event loop."""

    async def run():
        conn = await asyncpg.connect(DATABASE_URL, statement_cache_size=0)
        try:
            return await query(conn)
        finally:
            await conn.close()

    return asyncio.run(run())


@pytest.fixture
def seeded():
    """Five pending pickups reporting in 2 to 3 hours, two 3-seat vans."""
    now = datetime.now(UTC)

    async def seed(conn):
        crew, pickups = [], []
        for n, (lat, lon) in enumerate(CREW):
            point = f"SRID=4326;POINT({lon} {lat})"
            crew_id = await conn.fetchval(
                """
                insert into public.crew_members (name, role, home_location)
                values ($1, 'cabin_crew', $2) returning id
                """,
                f"test-{RUN} crew {n}",
                point,
            )
            crew.append(crew_id)
            pickups.append(
                await conn.fetchval(
                    """
                    insert into public.pickup_requests
                        (crew_member_id, pickup_location, report_time, request_type)
                    values ($1, $2, $3, 'rostered') returning id
                    """,
                    crew_id,
                    point,
                    now + timedelta(hours=2, minutes=15 * n),
                )
            )
        vehicles = [
            await conn.fetchval(
                "insert into public.vehicles (plate_number, capacity) values ($1, $2) returning id",
                f"T{RUN}{v}",
                SEATS,
            )
            for v in range(2)
        ]
        return crew, pickups, vehicles

    crew, pickups, vehicles = db(seed)
    yield pickups, vehicles

    # Deletes only this run's rows: the jobs made under this run's keys and
    # their routes, and the ids seeded above. Never a whole table.
    async def clean(conn):
        async with conn.transaction():
            jobs = await conn.fetch(
                "select id from public.optimization_jobs where idempotency_key like $1",
                f"test-{RUN}-%",
            )
            job_ids = [j["id"] for j in jobs]
            await conn.execute(
                "delete from public.optimization_job_pickups where optimization_job_id = any($1)",
                job_ids,
            )
            await conn.execute(
                """
                delete from public.route_nodes where route_id in
                    (select id from public.routes where optimization_job_id = any($1))
                """,
                job_ids,
            )
            await conn.execute(
                "delete from public.routes where optimization_job_id = any($1)", job_ids
            )
            await conn.execute("delete from public.optimization_jobs where id = any($1)", job_ids)
            await conn.execute("delete from public.pickup_requests where id = any($1)", pickups)
            await conn.execute("delete from public.crew_members where id = any($1)", crew)
            await conn.execute("delete from public.vehicles where id = any($1)", vehicles)

    db(clean)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "database_url", DATABASE_URL)
    monkeypatch.setattr(settings, "travel_model", "haversine")
    monkeypatch.setattr(settings, "solve_time_limit_sec", 1.0)
    monkeypatch.setattr(settings, "solver_pool_size", 1)
    with TestClient(app) as client:
        yield client


def post(client, pickups, vehicles, key):
    return client.post(
        "/optimisation-jobs",
        json={
            "trigger_type": "scheduled",
            "pickup_request_ids": [str(p) for p in pickups],
            "vehicle_ids": [str(v) for v in vehicles],
        },
        headers={"Idempotency-Key": f"test-{RUN}-{key}"},
    )


def run_job(client, pickups, vehicles, key) -> dict:
    accepted = post(client, pickups, vehicles, key)
    assert accepted.status_code == 202, accepted.text
    result = wait_for_job(client, accepted.json()["id"])
    assert result["status"] == "completed", result["error"]
    return result


def test_completed_job_writes_routes_nodes_and_outcomes(client, seeded):
    pickups, vehicles = seeded
    result = run_job(client, pickups, vehicles, "write")

    async def read(conn):
        return (
            await conn.fetch(
                "select id, status from public.pickup_requests where id = any($1)", pickups
            ),
            await conn.fetch(
                """
                select n.pickup_request_id, r.total_distance_km
                from public.route_nodes n join public.routes r on r.id = n.route_id
                where r.optimization_job_id = $1 and n.superseded_at is null
                """,
                result["id"],
            ),
            await conn.fetch(
                """
                select pickup_request_id, outcome from public.optimization_job_pickups
                where optimization_job_id = $1
                """,
                result["id"],
            ),
            await conn.fetchval(
                "select finished_at from public.optimization_jobs where id = $1", result["id"]
            ),
        )

    statuses, nodes, outcomes, finished_at = db(read)
    routed = {n["pickup_request_id"] for n in nodes}
    unassigned = {o["pickup_request_id"] for o in outcomes if o["outcome"] == "unassigned"}
    # Every requested pickup has an outcome; routed ones are assigned.
    assert {o["pickup_request_id"] for o in outcomes} == set(pickups)
    assert routed | unassigned == set(pickups) and not routed & unassigned
    assert {s["id"] for s in statuses if s["status"] == "assigned"} == routed
    # PostGIS measured each route: depot, stops and JKIA are kilometres apart.
    assert all(n["total_distance_km"] > 5 for n in nodes)
    assert finished_at is not None
    # GET returns the same plan.
    assert {n["pickup_request_id"] for r in result["routes"] for n in r["nodes"]} == {
        str(p) for p in routed
    }


def test_second_job_supersedes_the_first_and_leaves_one_live_node_per_pickup(client, seeded):
    pickups, vehicles = seeded
    first = run_job(client, pickups, vehicles, "first")
    second = run_job(client, pickups, vehicles, "second")

    async def read(conn):
        return await conn.fetch(
            """
            select n.pickup_request_id, n.superseded_at, r.optimization_job_id, r.status
            from public.route_nodes n join public.routes r on r.id = n.route_id
            where n.pickup_request_id = any($1)
            """,
            pickups,
        )

    nodes = db(read)
    first_nodes = [n for n in nodes if str(n["optimization_job_id"]) == first["id"]]
    live = [n for n in nodes if n["superseded_at"] is None]

    assert first_nodes, "the first job routed someone"
    assert all(n["superseded_at"] is not None for n in first_nodes)
    assert all(n["status"] == "superseded" for n in first_nodes)
    assert all(str(n["optimization_job_id"]) == second["id"] for n in live)
    live_pickups = [n["pickup_request_id"] for n in live]
    assert len(live_pickups) == len(set(live_pickups)), "one live node per pickup"
    # The first job's result still shows what it planned.
    assert client.get(f"/optimisation-jobs/{first['id']}").json()["routes"] == first["routes"]


def live_nodes(pickups) -> list:
    async def read(conn):
        return await conn.fetch(
            """
            select n.pickup_request_id, r.optimization_job_id, r.status
            from public.route_nodes n join public.routes r on r.id = n.route_id
            where n.pickup_request_id = any($1) and n.superseded_at is null
            """,
            pickups,
        )

    return db(read)


def job_count(key) -> int:
    async def count(conn):
        return await conn.fetchval(
            "select count(*) from public.optimization_jobs where idempotency_key = $1",
            f"test-{RUN}-{key}",
        )

    return db(count)


def test_partial_replan_of_a_route_is_a_conflict_and_a_full_one_succeeds(client, seeded):
    pickups, vehicles = seeded
    p1, p2 = pickups[:2]
    # One van with room for both: P1 and P2 share its route.
    first = run_job(client, [p1, p2], vehicles[:1], "pair")
    assert len(first["routes"]) == 1 and len(first["routes"][0]["nodes"]) == 2

    # P1 alone would leave P2 on a superseded route.
    partial = post(client, [p1], vehicles[:1], "p1-only")
    assert partial.status_code == 409
    assert partial.json()["detail"] == {"pickup_request_ids_left_behind": [str(p2)]}
    assert job_count("p1-only") == 0

    # Both together replace the route: one live node each, on the new job's.
    second = run_job(client, [p1, p2], vehicles[:1], "pair-again")
    live = live_nodes([p1, p2])
    assert sorted(n["pickup_request_id"] for n in live) == sorted([p1, p2])
    assert all(str(n["optimization_job_id"]) == second["id"] for n in live)
    assert all(n["status"] == "active" for n in live)


def test_pickup_on_a_departed_route_is_a_conflict_and_creates_no_job(client, seeded):
    pickups, vehicles = seeded
    first = run_job(client, pickups, vehicles, "before")
    routed = {n["pickup_request_id"] for r in first["routes"] for n in r["nodes"]}

    # Later than every first stop: every route of the first job has left.
    runner = app.state.job_runner
    runner.now = lambda: datetime.now(UTC) + timedelta(hours=4)
    response = post(client, pickups, vehicles, "after")

    assert response.status_code == 409
    assert set(response.json()["detail"]["pickup_request_ids_on_departed_routes"]) == routed
    assert job_count("after") == 0
