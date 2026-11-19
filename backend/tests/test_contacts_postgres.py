"""Contact numbers for the Call buttons (#255) against Postgres with the
migrations: who gets a number, and when.

- Crew C (with an account) has a pickup on driver A's van. C's GET
  /crew/me/pickup has A's first name once the route plans it, and A's number
  only from 30 minutes before the scheduled pickup until the pickup is
  confirmed, missed or cancelled. A's GET /drivers/me/route has C's number
  in the same window.
- Driver B and crew E are unrelated: the functions give them nothing.
- No signed-in user can select a phone column straight from the tables, as
  PostgREST would (it runs queries as the authenticated role).

They insert auth.users rows, so they run only on a throwaway database (CI's
PostGIS service), never against a Supabase host.
"""

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
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

KEY = SigningKey("contacts-key")
RUN = uuid4().hex[:6]
HOME = "SRID=4326;POINT(36.812 -1.2675)"
A_PHONE, C_PHONE = "+254700000901", "+254700000902"
NAMES = {"A": "Alice", "B": "Bob", "C": "Cate", "E": "Eve"}


def db(query):
    async def run():
        conn = await asyncpg.connect(DATABASE_URL, statement_cache_size=0)
        try:
            return await query(conn)
        finally:
            await conn.close()

    return asyncio.run(run())


def as_user(user_id, sql: str, *args):
    """sql run as a signed-in user, as PostgREST runs it: role
    authenticated, with the user's id in the JWT claims."""

    async def run(conn):
        async with conn.transaction():
            await conn.execute("set local role authenticated")
            await conn.execute(
                "select set_config('request.jwt.claim.sub', $1, true), "
                "set_config('request.jwt.claims', $2, true)",
                str(user_id),
                json.dumps({"sub": str(user_id), "role": "authenticated"}),
            )
            return await conn.fetch(sql, *args)

    return db(run)


@pytest.fixture
def world():
    """Build it with world(eta): the stop's scheduled pickup eta from now."""
    ids = {name: uuid4() for name in ("A", "B", "C", "E")}
    made: dict = {}

    def build(eta: timedelta) -> dict:
        async def seed(conn):
            async with conn.transaction():
                for name, uid in ids.items():
                    role = "driver" if name in "AB" else "crew"
                    phone = {"A": A_PHONE, "B": "+254700000903"}.get(name)
                    await conn.execute("insert into auth.users (id) values ($1)", uid)
                    await conn.execute(
                        "insert into public.profiles (id, role, full_name, phone) "
                        "values ($1, $2, $3, $4)",
                        uid,
                        role,
                        f"{NAMES[name]} test-{RUN}",
                        phone,
                    )
                for name in "CE":
                    made[f"crew{name}"] = await conn.fetchval(
                        "insert into public.crew_members (profile_id, name, role, "
                        "home_location, phone) values ($1, $2, 'cabin_crew', $3, $4) returning id",
                        ids[name],
                        f"test-{RUN} {name}",
                        HOME,
                        C_PHONE if name == "C" else "+254700000904",
                    )
                made["job"] = await conn.fetchval(
                    "insert into public.optimization_jobs (trigger_type, status) "
                    "values ('scheduled', 'completed') returning id"
                )
                for name in "AB":
                    made[f"van{name}"] = await conn.fetchval(
                        "insert into public.vehicles (assigned_driver_id, plate_number, capacity)"
                        " values ($1, $2, 14) returning id",
                        ids[name],
                        f"test-{RUN}-{name}",
                    )
                made["pickup"] = await conn.fetchval(
                    "insert into public.pickup_requests (crew_member_id, pickup_location, "
                    "report_time, request_type) values ($1, $2, now() + interval '3 hours', "
                    "'rostered') returning id",
                    made["crewC"],
                    HOME,
                )
                made["route"] = await conn.fetchval(
                    "insert into public.routes (vehicle_id, optimization_job_id, "
                    "total_distance_km, status, planned_departure, planned_arrival) "
                    "values ($1, $2, 21.5, 'active', now(), now() + interval '2 hours') "
                    "returning id",
                    made["vanA"],
                    made["job"],
                )
                made["node"] = await conn.fetchval(
                    "insert into public.route_nodes (route_id, pickup_request_id, seq_order, "
                    "estimated_arrival) values ($1, $2, 1, $3) returning id",
                    made["route"],
                    made["pickup"],
                    datetime.now(UTC) + eta,
                )

        db(seed)
        return made

    build.ids = ids
    yield build

    async def clean(conn):
        async with conn.transaction():
            await conn.execute(
                "delete from public.route_nodes where route_id = $1", made.get("route")
            )
            await conn.execute("delete from public.routes where id = $1", made.get("route"))
            await conn.execute(
                "delete from public.optimization_jobs where id = $1", made.get("job")
            )
            await conn.execute(
                "delete from public.pickup_requests where id = $1", made.get("pickup")
            )
            await conn.execute(
                "delete from public.vehicles where id = any($1)",
                [made.get("vanA"), made.get("vanB")],
            )
            await conn.execute(
                "delete from public.crew_members where id = any($1)",
                [made.get("crewC"), made.get("crewE")],
            )
            await conn.execute("delete from public.profiles where id = any($1)", list(ids.values()))
            await conn.execute("delete from auth.users where id = any($1)", list(ids.values()))

    db(clean)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "database_url", DATABASE_URL)
    monkeypatch.setattr(settings, "travel_model", "haversine")
    monkeypatch.setattr(settings, "solver_pool_size", 1)
    monkeypatch.setattr(app.state, "jwt_keys", FakeJwks(KEY).source(), raising=False)
    monkeypatch.setattr(app.state, "jwt_issuer", ISSUER, raising=False)
    with TestClient(app) as client:
        yield client


def seen(client, ids) -> tuple:
    """(driver's first name and number on C's pickup, C's number on A's stop)."""
    crew = client.get("/crew/me/pickup", headers=bearer(KEY.token(ids["C"])))
    driver = client.get("/drivers/me/route", headers=bearer(KEY.token(ids["A"])))
    assert crew.status_code == driver.status_code == 200, (crew.text, driver.text)
    pickup = crew.json()["pickup"]
    [stop] = driver.json()["route"]["stops"]
    return pickup["driver_first_name"], pickup["driver_phone"], stop["crew_phone"]


def test_in_the_window_each_side_gets_the_other_ones_number(client, world):
    world(timedelta(minutes=20))
    assert seen(client, world.ids) == ("Alice", A_PHONE, C_PHONE)


def test_before_the_window_the_numbers_are_not_in_the_responses(client, world):
    world(timedelta(minutes=45))
    assert seen(client, world.ids) == ("Alice", None, None)


@pytest.mark.parametrize("status", ["picked_up", "missed", "cancelled"])
def test_once_the_pickup_is_done_the_numbers_go(world, status):
    made = world(timedelta(minutes=5))
    db(
        lambda conn: conn.execute(
            "update public.pickup_requests set status = $2 where id = $1", made["pickup"], status
        )
    )
    ids = world.ids
    [contact] = as_user(ids["C"], "select * from private.driver_contact($1)", made["pickup"])
    assert tuple(contact) == ("Alice", None)
    [row] = as_user(ids["A"], "select private.crew_phone($1)", made["node"])
    assert row[0] is None


def test_an_unrelated_driver_or_crew_member_gets_nothing(world):
    made = world(timedelta(minutes=5))
    ids = world.ids
    [row] = as_user(ids["B"], "select private.crew_phone($1)", made["node"])
    assert row[0] is None  # B's van doesn't have this stop
    assert as_user(ids["E"], "select * from private.driver_contact($1)", made["pickup"]) == []
    # The same calls by the right people do give the numbers.
    assert as_user(ids["A"], "select private.crew_phone($1)", made["node"])[0][0] == C_PHONE
    assert (
        as_user(ids["C"], "select * from private.driver_contact($1)", made["pickup"])[0][1]
        == A_PHONE
    )


@pytest.mark.parametrize("table", ["profiles", "crew_members"])
def test_a_signed_in_user_cant_select_a_phone_column_directly(world, table):
    """What a PostgREST select of phone does: permission denied."""
    world(timedelta(minutes=5))
    driver = world.ids["A"]
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        as_user(driver, f"select phone from public.{table}")
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        as_user(driver, f"select * from public.{table}")
    # The other columns still read as before, under RLS.
    assert as_user(driver, f"select id from public.{table}") is not None
