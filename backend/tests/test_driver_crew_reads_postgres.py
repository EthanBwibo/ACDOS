"""Driver and crew read endpoints (#52) against Postgres with the migrations.

They insert auth.users rows, so they run only on a throwaway database: when
DATABASE_URL is set in the environment (CI's PostGIS service sets it), and
never against a Supabase host. backend/.env alone does not run them.

Through the HTTP API, with tokens signed by a test key (tests/jwt_keys.py),
so what is tested is what the app does: verify the token, look up the role,
switch to the caller, and let RLS filter.

Seeded world (fresh ids each run, deleted afterwards by id):
- driver A drives van VA: active route rA (crew F then crew C, plus a
  superseded stop for crew E that a live route never shows), an older
  superseded route rA_old that held crew C, and four more active routes
  later in the day (for pagination);
- driver B drives van VB: active route rB (crew E);
- driver H has no van; dispatcher D; a user N with no profile;
- crew C and E have accounts; crew F does not.
"""

import asyncio
import csv
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app import reads
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

ZONES_CSV = Path(__file__).resolve().parents[2] / "data" / "pickup_zones.csv"
KEY = SigningKey("test-key")
NOW = datetime.now(UTC)

# Pickup points: near Westlands, Kilimani and South B. C has 6 decimals, so
# the driver's 5-decimal rounding shows.
POINTS = {"C": (-1.267512, 36.812034), "E": (-1.2921, 36.7870), "F": (-1.3100, 36.8340)}


def db(query):
    async def run():
        conn = await asyncpg.connect(DATABASE_URL, statement_cache_size=0)
        try:
            return await query(conn)
        finally:
            await conn.close()

    return asyncio.run(run())


def point(lat_lon) -> str:
    lat, lon = lat_lon
    return f"SRID=4326;POINT({lon} {lat})"


@pytest.fixture(scope="module")
def world():
    ids = {name: uuid4() for name in ["A", "B", "H", "D", "N", "C", "E"]}
    rows: dict[str, list] = {
        "crew": [],
        "pickups": [],
        "vehicles": [],
        "jobs": [],
        "routes": [],
        "nodes": [],
    }
    w = {"users": ids, "rows": rows}

    async def seed(conn):
        async with conn.transaction():
            await conn.executemany(
                "insert into auth.users (id) values ($1)", [(i,) for i in ids.values()]
            )
            await conn.executemany(
                "insert into public.profiles (id, role, full_name) values ($1, $2, $3)",
                [
                    (ids["A"], "driver", "Driver A"),
                    (ids["B"], "driver", "Driver B"),
                    (ids["H"], "driver", "Driver H"),
                    (ids["D"], "dispatcher", "Dispatcher D"),
                    (ids["C"], "crew", "Crew C"),
                    (ids["E"], "crew", "Crew E"),
                ],
            )

            async def crew(name, profile):
                cid = await conn.fetchval(
                    "insert into public.crew_members (profile_id, name, role, home_location) "
                    "values ($1, $2, 'cabin_crew', $3) returning id",
                    profile,
                    f"Crew {name}",
                    point(POINTS[name]),
                )
                rows["crew"].append(cid)
                return cid

            crew_ids = {"C": await crew("C", ids["C"]), "E": await crew("E", ids["E"])}
            crew_ids["F"] = await crew("F", None)

            async def pickup(name, report_in):
                pid = await conn.fetchval(
                    "insert into public.pickup_requests "
                    "(crew_member_id, pickup_location, report_time, request_type, status) "
                    "values ($1, $2, $3, 'rostered', 'assigned') returning id",
                    crew_ids[name],
                    point(POINTS[name]),
                    NOW + report_in,
                )
                rows["pickups"].append(pid)
                return pid

            async def van(plate, driver):
                vid = await conn.fetchval(
                    "insert into public.vehicles (assigned_driver_id, plate_number, capacity) "
                    "values ($1, $2, 14) returning id",
                    driver,
                    plate,
                )
                rows["vehicles"].append(vid)
                return vid

            run = uuid4().hex[:6]
            w["plates"] = {"A": f"KAA {run}A", "B": f"KBB {run}B"}
            va, vb = await van(w["plates"]["A"], ids["A"]), await van(w["plates"]["B"], ids["B"])
            job = await conn.fetchval(
                "insert into public.optimization_jobs (trigger_type, status) "
                "values ('scheduled', 'completed') returning id"
            )
            rows["jobs"].append(job)

            async def route(vehicle, status, stops):
                """stops: [(pickup id, ETA from now, superseded)]"""
                rid = await conn.fetchval(
                    "insert into public.routes "
                    "(vehicle_id, optimization_job_id, total_distance_km, status) "
                    "values ($1, $2, 21.5, $3) returning id",
                    vehicle,
                    job,
                    status,
                )
                rows["routes"].append(rid)
                for seq, (pid, eta_in, superseded) in enumerate(stops, start=1):
                    rows["nodes"].append(
                        await conn.fetchval(
                            "insert into public.route_nodes (route_id, pickup_request_id, "
                            "seq_order, estimated_arrival, superseded_at) "
                            "values ($1, $2, $3, $4, $5) returning id",
                            rid,
                            pid,
                            seq,
                            NOW + eta_in,
                            NOW - timedelta(hours=1) if superseded else None,
                        )
                    )
                return rid

            p = {
                "C": await pickup("C", timedelta(hours=3)),
                "E": await pickup("E", timedelta(hours=3)),
                "F": await pickup("F", timedelta(hours=3)),
            }
            w["pickups"] = p
            w["routes"] = {
                "A_old": await route(va, "superseded", [(p["C"], timedelta(minutes=50), True)]),
                "A": await route(
                    va,
                    "active",
                    [
                        (p["F"], timedelta(hours=1), False),
                        (p["C"], timedelta(hours=1, minutes=20), False),
                        # Replaced on a route still active: no live route
                        # should show it (#51 never leaves one; nothing stops it).
                        (p["E"], timedelta(hours=1, minutes=30), True),
                    ],
                ),
                "B": await route(vb, "active", [(p["E"], timedelta(hours=1, minutes=5), False)]),
            }
            # Four later routes for driver A, one stop each (crew F's later duties).
            w["later_A"] = [
                await route(
                    va,
                    "active",
                    [(await pickup("F", timedelta(hours=4 + k)), timedelta(hours=3 + k), False)],
                )
                for k in range(4)
            ]

    db(seed)
    yield w

    async def clean(conn):
        async with conn.transaction():
            await conn.execute("delete from public.route_nodes where id = any($1)", rows["nodes"])
            await conn.execute("delete from public.routes where id = any($1)", rows["routes"])
            await conn.execute(
                "delete from public.optimization_jobs where id = any($1)", rows["jobs"]
            )
            await conn.execute(
                "delete from public.pickup_requests where id = any($1)", rows["pickups"]
            )
            await conn.execute("delete from public.vehicles where id = any($1)", rows["vehicles"])
            await conn.execute("delete from public.crew_members where id = any($1)", rows["crew"])
            await conn.execute("delete from public.profiles where id = any($1)", list(ids.values()))
            await conn.execute("delete from auth.users where id = any($1)", list(ids.values()))

    db(clean)


@pytest.fixture
def client(monkeypatch, world):
    monkeypatch.setattr(settings, "database_url", DATABASE_URL)
    monkeypatch.setattr(settings, "travel_model", "haversine")
    monkeypatch.setattr(settings, "solver_pool_size", 1)
    monkeypatch.setattr(app.state, "jwt_keys", FakeJwks(KEY).source(), raising=False)
    monkeypatch.setattr(app.state, "jwt_issuer", ISSUER, raising=False)
    with TestClient(app) as client:
        yield client


def as_user(world, name) -> dict:
    return bearer(KEY.token(world["users"][name]))


def keys_anywhere(value) -> set[str]:
    if isinstance(value, dict):
        return set(value) | set().union(*(keys_anywhere(v) for v in value.values()))
    if isinstance(value, list):
        return set().union(*(keys_anywhere(v) for v in value))
    return set()


def test_pickup_zones_match_the_csv_exactly():
    with ZONES_CSV.open(newline="", encoding="utf-8") as f:
        expected = {r["zone"]: (float(r["lat"]), float(r["lon"])) for r in csv.DictReader(f)}

    async def read(conn):
        return await conn.fetch(
            "select label, extensions.st_y(location::extensions.geometry) as lat, "
            "extensions.st_x(location::extensions.geometry) as lon from public.pickup_zones"
        )

    assert {r["label"]: (r["lat"], r["lon"]) for r in db(read)} == expected


def test_driver_gets_their_current_route_with_live_stops_only(client, world):
    body = client.get("/drivers/me/route", headers=as_user(world, "A")).json()["route"]

    assert body["route_id"] == str(world["routes"]["A"])
    assert body["vehicle_plate"] == world["plates"]["A"]
    assert [s["crew_name"] for s in body["stops"]] == ["Crew F", "Crew C"]
    assert [s["seq_order"] for s in body["stops"]] == [1, 2]
    stop_c = body["stops"][1]
    assert (stop_c["lat"], stop_c["lon"]) == (round(POINTS["C"][0], 5), round(POINTS["C"][1], 5))
    assert stop_c["zone_label"] == "Westlands, Nairobi"
    assert stop_c["eta"] is None
    # Exactly what the driver's screen shows, no more.
    assert set(stop_c) == {
        "route_node_id", "seq_order", "crew_name", "zone_label",
        "scheduled_pickup", "eta", "lat", "lon",
    }  # fmt: skip


def test_drivers_cannot_read_each_others_routes(client, world):
    a = client.get("/drivers/me/route", headers=as_user(world, "A")).json()["route"]
    b = client.get("/drivers/me/route", headers=as_user(world, "B")).json()["route"]

    assert b["route_id"] == str(world["routes"]["B"])
    assert [s["crew_name"] for s in b["stops"]] == ["Crew E"]
    assert {s["route_node_id"] for s in a["stops"]}.isdisjoint(
        s["route_node_id"] for s in b["stops"]
    )
    b_schedule = client.get("/drivers/me/routes", headers=as_user(world, "B")).json()
    assert [i["route_id"] for i in b_schedule["items"]] == [str(world["routes"]["B"])]


def test_a_driver_without_a_route_gets_null(client, world):
    response = client.get("/drivers/me/route", headers=as_user(world, "H"))
    assert response.status_code == 200
    assert response.json() == {"route": None}


def test_the_schedule_is_paginated_without_gaps_or_repeats(client, world):
    seen, cursor, pages = [], None, 0
    while True:
        # Bounded: a cursor that never moves on must fail here, not hang.
        assert pages < 10, "the schedule never reached its last page"
        params = {"limit": 2} | ({"cursor": cursor} if cursor else {})
        page = client.get("/drivers/me/routes", headers=as_user(world, "A"), params=params).json()
        pages += 1
        assert len(page["items"]) <= 2
        seen += page["items"]
        cursor = page["next_cursor"]
        if cursor is None:
            break

    expected = [world["routes"]["A"], *world["later_A"]]  # in time order; not A_old
    assert [i["route_id"] for i in seen] == [str(r) for r in expected]
    assert pages == 3
    assert [i["first_pickup"] for i in seen] == sorted(i["first_pickup"] for i in seen)


@pytest.mark.parametrize(
    "params", [{"cursor": "not-a-cursor"}, {"limit": 0}, {"limit": 51}], ids=str
)
def test_bad_page_parameters_are_422(client, world, params):
    response = client.get("/drivers/me/routes", headers=as_user(world, "A"), params=params)
    assert response.status_code == 422


def test_crew_get_their_next_pickup_without_coordinates(client, world):
    body = client.get("/crew/me/pickup", headers=as_user(world, "C")).json()["pickup"]

    assert body["pickup_request_id"] == str(world["pickups"]["C"])
    assert body["vehicle_plate"] == world["plates"]["A"]
    assert body["status"] == "assigned"
    assert body["eta"] is None
    assert body["scheduled_pickup"] is not None
    assert set(body) == {
        "pickup_request_id", "status", "report_time", "scheduled_pickup", "eta", "vehicle_plate",
    }  # fmt: skip
    assert not keys_anywhere(body) & {"lat", "lon", "location", "pickup_location"}


def test_crew_cannot_read_each_others_pickups(client, world):
    c = client.get("/crew/me/pickup", headers=as_user(world, "C")).json()["pickup"]
    e = client.get("/crew/me/pickup", headers=as_user(world, "E")).json()["pickup"]

    assert e["pickup_request_id"] == str(world["pickups"]["E"])
    assert e["vehicle_plate"] == world["plates"]["B"]
    assert c["pickup_request_id"] != e["pickup_request_id"]


@pytest.mark.parametrize(
    ("user", "path"),
    [
        ("C", "/drivers/me/route"),
        ("C", "/drivers/me/routes"),
        ("A", "/crew/me/pickup"),
        ("D", "/drivers/me/route"),
        ("D", "/crew/me/pickup"),
        ("N", "/drivers/me/route"),
        ("N", "/crew/me/pickup"),
    ],
)
def test_the_wrong_role_or_no_profile_is_403(client, world, user, path):
    assert client.get(path, headers=as_user(world, user)).status_code == 403


def test_no_token_is_401(client):
    assert client.get("/drivers/me/route").status_code == 401


# Each policy #52 adds is needed: with it dropped (inside a transaction that
# is rolled back), the same read as the same user comes back empty.


def with_policy_changed(change_sql, user_id, read):
    async def run(conn):
        tx = conn.transaction()
        await tx.start()
        try:
            await conn.execute(change_sql)
            await reads.become(conn, user_id)
            return await read(conn)
        finally:
            await tx.rollback()

    return db(run)


def test_crew_need_the_vehicle_policy_to_see_their_plate(world):
    crew_c = world["rows"]["crew"][0]

    def plate(conn):
        return reads.next_pickup(conn, crew_c, NOW)

    assert with_policy_changed("select 1", world["users"]["C"], plate).vehicle_plate
    dropped = with_policy_changed(
        "drop policy vehicles_crew_select on public.vehicles", world["users"]["C"], plate
    )
    assert dropped.vehicle_plate is None


def test_crew_need_the_route_policy_to_see_their_plate(world):
    crew_c = world["rows"]["crew"][0]
    dropped = with_policy_changed(
        "drop policy routes_crew_select on public.routes",
        world["users"]["C"],
        lambda conn: reads.next_pickup(conn, crew_c, NOW),
    )
    assert dropped.vehicle_plate is None


def test_drivers_need_the_zone_policy_to_see_zone_labels(world):
    dropped = with_policy_changed(
        "drop policy pickup_zones_authenticated_select on public.pickup_zones",
        world["users"]["A"],
        lambda conn: reads.current_route(conn, world["users"]["A"]),
    )
    assert [s.zone_label for s in dropped.stops] == [None, None]


def test_the_driver_node_policy_hides_superseded_stops(world):
    # The endpoint's own SQL also filters superseded_at (a second check), so
    # the policy is tested on its own: what driver A can read of rA_old.
    async def count(conn):
        return await conn.fetchval(
            "select count(*) from public.route_nodes where route_id = $1",
            world["routes"]["A_old"],
        )

    driver = world["users"]["A"]
    assert with_policy_changed("select 1", driver, count) == 0
    before_021 = """
        alter policy route_nodes_driver_select on public.route_nodes using (
            route_id in (
                select r.id from public.routes r
                join public.vehicles v on v.id = r.vehicle_id
                where v.assigned_driver_id = (select auth.uid())
            )
        )
    """
    assert with_policy_changed(before_021, driver, count) == 1


def test_reads_run_as_the_caller_and_leave_the_connection_clean(world):
    # The endpoints' SQL also filters by the caller, so without the switch to
    # the caller they would still look right: check the switch itself.
    user = world["users"]["C"]

    async def run():
        pool = await asyncpg.create_pool(
            DATABASE_URL, statement_cache_size=0, min_size=1, max_size=1
        )
        try:
            async with reads.as_caller(pool, user) as (conn, profile):
                inside = await conn.fetchrow("select current_user as who, auth.uid() as uid")
            async with pool.acquire() as conn:  # the same single connection, reused
                after = await conn.fetchrow(
                    "select current_user as who, "
                    "current_setting('request.jwt.claim.sub', true) as sub"
                )
            return profile, inside, after
        finally:
            await pool.close()

    profile, inside, after = asyncio.run(run())
    assert profile == reads.Profile("crew", world["rows"]["crew"][0])
    assert (inside["who"], inside["uid"]) == ("authenticated", user)
    assert after["who"] == "postgres" and not after["sub"]


def test_the_sql_filters_hold_without_rls(world):
    # The reads repeat the caller filter in SQL as a second check. Run as
    # postgres, which bypasses RLS, the filters alone must keep everyone
    # else's rows out.
    users, crew = world["users"], world["rows"]["crew"]

    async def read(conn):
        return (
            await reads.current_route(conn, users["A"]),
            await reads.route_page(conn, users["B"], None, 50),
            await reads.next_pickup(conn, crew[0], NOW),
        )

    route_a, page_b, pickup_c = db(read)
    assert [s.crew_name for s in route_a.stops] == ["Crew F", "Crew C"]  # not E's superseded stop
    assert [i.route_id for i in page_b.items] == [world["routes"]["B"]]
    assert pickup_c.pickup_request_id == world["pickups"]["C"]


def test_drivers_see_no_pickup_or_crew_behind_a_superseded_stop(world):
    # Crew E's superseded stop sits on driver A's active route. Through the
    # driver helper (fixed in 021), A must not read E's pickup or name.
    async def visible(conn):
        return (
            await conn.fetchval(
                "select count(*) from public.pickup_requests where id = $1",
                world["pickups"]["E"],
            ),
            await conn.fetchval("select count(*) from public.crew_members where name = 'Crew E'"),
        )

    driver = world["users"]["A"]
    assert with_policy_changed("select 1", driver, visible) == (0, 0)
    helper_before_021 = """
        create or replace function private.driver_active_pickup_request_ids()
        returns setof uuid language sql stable security definer set search_path = ''
        as $$
            select n.pickup_request_id
            from public.route_nodes n
            join public.routes r on r.id = n.route_id
            join public.vehicles v on v.id = r.vehicle_id
            where r.status = 'active' and v.assigned_driver_id = auth.uid();
        $$
    """
    assert with_policy_changed(helper_before_021, driver, visible) == (1, 1)
