"""The dispatcher's dashboard endpoints (#136) against Postgres with the
migrations.

They insert auth.users rows, so they run only on a throwaway database: when
DATABASE_URL is set in the environment (CI's PostGIS service sets it), and
never against a Supabase host. Through the HTTP API, with tokens signed by a
test key, so the role check and RLS are what the app really does.

Seeded world (fresh ids each run, deleted afterwards by id):
- dispatcher D and driver A;
- crew near Westlands, Kilimani and South B with pickups on DAY (a fixed
  day far ahead, so no other rows share it), at 05:00, 06:30 and 08:00
  Nairobi time; Westlands' is picked_up. Two more pickups just outside DAY:
  23:59 the day before and 00:00 the day after;
- van VA, driven by A, on the road now (its route left 10 minutes ago), and
  van VB at the depot;
- on DAY: an active route rDay on VB (Kilimani's stop live, Westlands' stop
  superseded) and a superseded route; an active route the day after;
- schedule-change notices (#53): none for Westlands, one not acknowledged
  for Kilimani, two acknowledged for South B (the later one at ACKED).
"""

import asyncio
import os
from datetime import UTC, date, datetime, time, timedelta
from urllib.parse import urlsplit
from uuid import uuid4

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.jobs.worker import EAT
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

KEY = SigningKey("dispatcher-key")
NOW = datetime.now(UTC)
DAY = date(2031, 3, 4)
ACKED = datetime(2031, 3, 3, 18, 0, tzinfo=UTC)
RUN = uuid4().hex[:6]
POINTS = {
    "Westlands": (-1.2675, 36.8120),
    "Kilimani": (-1.2893, 36.7869),
    "South B": (-1.3103, 36.8337),
}


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), EAT)


def db(query):
    async def run():
        conn = await asyncpg.connect(DATABASE_URL, statement_cache_size=0)
        try:
            return await query(conn)
        finally:
            await conn.close()

    return asyncio.run(run())


def point(name: str) -> str:
    lat, lon = POINTS[name]
    return f"SRID=4326;POINT({lon} {lat})"


@pytest.fixture(scope="module")
def world():
    users = {"D": uuid4(), "A": uuid4()}
    rows: dict[str, list] = {
        k: [] for k in ["crew", "pickups", "vehicles", "jobs", "routes", "nodes", "notices"]
    }
    w: dict = {"users": users, "rows": rows, "pickups": {}, "vans": {}, "routes": {}}

    async def seed(conn):
        async with conn.transaction():
            for name, uid in users.items():
                await conn.execute("insert into auth.users (id) values ($1)", uid)
                await conn.execute(
                    "insert into public.profiles (id, role, full_name) values ($1, $2, $3)",
                    uid,
                    "dispatcher" if name == "D" else "driver",
                    f"test-{RUN} {name}",
                )

            async def pickup(key, zone, report, status="assigned"):
                crew = await conn.fetchval(
                    "insert into public.crew_members (name, role, home_location) "
                    "values ($1, 'cabin_crew', $2) returning id",
                    f"Crew {key} {RUN}",
                    point(zone),
                )
                rows["crew"].append(crew)
                pid = await conn.fetchval(
                    "insert into public.pickup_requests "
                    "(crew_member_id, pickup_location, report_time, request_type, status) "
                    "values ($1, $2, $3, 'rostered', $4) returning id",
                    crew,
                    point(zone),
                    report,
                    status,
                )
                rows["pickups"].append(pid)
                w["pickups"][key] = pid

            await pickup("westlands", "Westlands", at(DAY, 5), "picked_up")
            await pickup("kilimani", "Kilimani", at(DAY, 6, 30))
            await pickup("south_b", "South B", at(DAY, 8), "pending")
            await pickup("before", "Kilimani", at(DAY - timedelta(days=1), 23, 59))
            await pickup("after", "Kilimani", at(DAY + timedelta(days=1), 0))
            await pickup("now", "South B", NOW + timedelta(hours=1))

            async def notice(key, issued, acknowledged):
                rows["notices"].append(
                    await conn.fetchval(
                        "insert into public.schedule_change_notices (pickup_request_id, "
                        "reason, previous_pickup_time, new_pickup_time, issued_at, "
                        "acknowledged_at) values ($1, 'vehicle_breakdown', $2, $2, $2, $3) "
                        "returning id",
                        w["pickups"][key],
                        issued,
                        acknowledged,
                    )
                )

            await notice("kilimani", at(DAY, 4), None)
            await notice("south_b", at(DAY, 3), ACKED - timedelta(hours=1))
            await notice("south_b", at(DAY, 4), ACKED)

            for van, driver in [("VA", users["A"]), ("VB", None)]:
                w["vans"][van] = await conn.fetchval(
                    "insert into public.vehicles (assigned_driver_id, plate_number, capacity) "
                    "values ($1, $2, 14) returning id",
                    driver,
                    f"TD{RUN}{van}",
                )
                rows["vehicles"].append(w["vans"][van])
            job = await conn.fetchval(
                "insert into public.optimization_jobs (trigger_type, status, idempotency_key) "
                "values ('scheduled', 'completed', $1) returning id",
                f"test-{RUN}-dispatcher",
            )
            rows["jobs"].append(job)

            async def route(key, van, departs, status, stops):
                rid = await conn.fetchval(
                    "insert into public.routes (vehicle_id, optimization_job_id, "
                    "total_distance_km, status, planned_departure, planned_arrival) "
                    "values ($1, $2, 31.5, $3, $4, $5) returning id",
                    w["vans"][van],
                    job,
                    status,
                    departs,
                    departs + timedelta(hours=1),
                )
                rows["routes"].append(rid)
                w["routes"][key] = rid
                for seq, (stop, superseded) in enumerate(stops, start=1):
                    rows["nodes"].append(
                        await conn.fetchval(
                            "insert into public.route_nodes (route_id, pickup_request_id, "
                            "seq_order, estimated_arrival, superseded_at) "
                            "values ($1, $2, $3, $4, $5) returning id",
                            rid,
                            w["pickups"][stop],
                            seq,
                            departs + timedelta(minutes=20 * seq),
                            NOW if superseded else None,
                        )
                    )

            await route("road", "VA", NOW - timedelta(minutes=10), "active", [("now", False)])
            await route(
                "day",
                "VB",
                at(DAY, 5, 30),
                "active",
                [("westlands", True), ("kilimani", False)],
            )
            await route("old", "VB", at(DAY, 4), "superseded", [("south_b", False)])
            await route(
                "next_day", "VB", at(DAY + timedelta(days=1), 4), "active", [("after", False)]
            )

    db(seed)
    yield w

    async def clean(conn):
        async with conn.transaction():
            await conn.execute(
                "delete from public.schedule_change_notices where id = any($1)", rows["notices"]
            )
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
            await conn.execute(
                "delete from public.profiles where id = any($1)", list(users.values())
            )
            await conn.execute("delete from auth.users where id = any($1)", list(users.values()))

    db(clean)


@pytest.fixture
def client(monkeypatch, world):
    monkeypatch.setattr(settings, "database_url", DATABASE_URL)
    monkeypatch.setattr(settings, "travel_model", "haversine")
    monkeypatch.setattr(settings, "solver_pool_size", 1)
    monkeypatch.setattr(app.state, "jwt_keys", FakeJwks(KEY).source(), raising=False)
    monkeypatch.setattr(app.state, "jwt_issuer", ISSUER, raising=False)
    with TestClient(app, headers=bearer(KEY.token(world["users"]["D"]))) as client:
        yield client


def walk(client, path: str, limit: int = 1) -> list[dict]:
    """Every item of a paginated list, one page of limit at a time."""
    items, cursor = [], None
    sep = "&" if "?" in path else "?"
    while True:
        query = f"{sep}limit={limit}" + (f"&cursor={cursor}" if cursor else "")
        response = client.get(path + query)
        assert response.status_code == 200, response.text
        body = response.json()
        assert len(body["items"]) <= limit
        items += body["items"]
        cursor = body["next_cursor"]
        if cursor is None:
            return items


ENDPOINTS = [
    ("GET", "/pickup-requests", None),
    ("PATCH", f"/pickup-requests/{uuid4()}", {"report_time": "2031-03-04T08:00:00Z"}),
    ("GET", "/vehicles", None),
    ("PATCH", f"/vehicles/{uuid4()}", {"status": "broken_down"}),
    ("GET", "/routes", None),
]


@pytest.mark.parametrize(("method", "path", "body"), ENDPOINTS)
def test_only_a_dispatcher_may_call_them(client, world, method, path, body):
    driver = bearer(KEY.token(world["users"]["A"]))
    response = client.request(method, path, json=body, headers=driver)
    assert (response.status_code, response.json()["code"]) == (403, "forbidden")


def test_the_days_pickups_in_report_order_with_their_zone(client, world):
    items = walk(client, f"/pickup-requests?date={DAY}")
    p = world["pickups"]
    assert [i["id"] for i in items] == [str(p[k]) for k in ["westlands", "kilimani", "south_b"]]
    first = items[0]
    assert first == {
        "id": str(p["westlands"]),
        "crew_name": f"Crew westlands {RUN}",
        "zone_label": "Westlands, Nairobi",
        "lat": round(POINTS["C"][0], 5),
        "lon": round(POINTS["C"][1], 5),
        "report_time": first["report_time"],
        "status": "picked_up",
        "needs_ack": False,
        "acknowledged_at": None,
    }
    assert datetime.fromisoformat(first["report_time"]) == at(DAY, 5)
    assert [i["zone_label"] for i in items[1:]] == ["Kilimani, Nairobi", "South B, Nairobi"]


def test_each_pickup_says_whether_its_notice_is_acknowledged(client, world):
    items = {i["id"]: i for i in walk(client, f"/pickup-requests?date={DAY}", 50)}
    p = world["pickups"]

    def ack(key):
        item = items[str(p[key])]
        at_ = item["acknowledged_at"]
        return item["needs_ack"], at_ and datetime.fromisoformat(at_)

    assert ack("westlands") == (False, None)  # no notices
    assert ack("kilimani") == (True, None)  # pending
    assert ack("south_b") == (False, ACKED)  # acknowledged: the latest one's time


def test_pages_of_any_size_give_the_same_pickups(client, world):
    path = f"/pickup-requests?date={DAY}"
    assert walk(client, path, limit=1) == walk(client, path, limit=2) == walk(client, path, 50)


def test_the_default_day_is_today_in_nairobi(client, world):
    today = datetime.now(EAT).date()
    for path in ["/pickup-requests", "/routes"]:
        assert walk(client, path, 50) == walk(client, f"{path}?date={today}", 50)
    assert str(world["pickups"]["now"]) in {
        i["id"]
        for i in walk(
            client, f"/pickup-requests?date={(NOW + timedelta(hours=1)).astimezone(EAT).date()}", 50
        )
    }


def test_vehicles_in_plate_order_with_whether_they_are_on_the_road(client, world):
    items = walk(client, "/vehicles")
    plates = [i["plate_number"] for i in items]
    assert plates == sorted(plates)
    assert len({i["id"] for i in items}) == len(items)
    ours = {i["plate_number"]: i for i in items if i["plate_number"].startswith(f"TD{RUN}")}
    assert ours == {
        f"TD{RUN}VA": {
            "id": str(world["vans"]["VA"]),
            "plate_number": f"TD{RUN}VA",
            "capacity": 14,
            "status": "available",
            "on_the_road": True,
        },
        f"TD{RUN}VB": {
            "id": str(world["vans"]["VB"]),
            "plate_number": f"TD{RUN}VB",
            "capacity": 14,
            "status": "available",
            "on_the_road": False,
        },
    }


def test_the_days_active_routes_with_live_stops_only(client, world):
    [route] = walk(client, f"/routes?date={DAY}")
    assert route["route_id"] == str(world["routes"]["day"])
    assert route["vehicle_id"] == str(world["vans"]["VB"])
    assert route["vehicle_plate"] == f"TD{RUN}VB"
    assert route["total_distance_km"] == 31.5
    assert datetime.fromisoformat(route["planned_departure"]) == at(DAY, 5, 30)
    assert datetime.fromisoformat(route["planned_arrival"]) == at(DAY, 6, 30)
    assert [(n["pickup_request_id"], n["seq_order"]) for n in route["nodes"]] == [
        (str(world["pickups"]["kilimani"]), 2)
    ]


def job_count() -> int:
    return db(lambda conn: conn.fetchval("select count(*) from public.optimization_jobs"))


def report_time(pickup) -> datetime:
    return db(
        lambda conn: conn.fetchval(
            "select report_time from public.pickup_requests where id = $1", pickup
        )
    )


def test_a_new_report_time_is_recorded_and_starts_no_job(client, world):
    pickup = world["pickups"]["kilimani"]
    jobs = job_count()
    delayed = at(DAY, 7, 30)
    try:
        response = client.patch(
            f"/pickup-requests/{pickup}", json={"report_time": delayed.isoformat()}
        )
        assert response.status_code == 200, response.text
        assert datetime.fromisoformat(response.json()["report_time"]) == delayed
        assert response.json()["status"] == "assigned"
        assert report_time(pickup) == delayed
        # Safe to retry: the same request again leaves the same row.
        again = client.patch(
            f"/pickup-requests/{pickup}", json={"report_time": delayed.isoformat()}
        )
        assert again.json() == response.json()
        assert job_count() == jobs
    finally:
        world_sql(
            "update public.pickup_requests set report_time = $2 where id = $1",
            pickup,
            at(DAY, 6, 30),
        )


def world_sql(query, *args):
    return db(lambda conn: conn.execute(query, *args))


def test_a_collected_pickups_report_time_is_refused(client, world):
    pickup = world["pickups"]["westlands"]
    response = client.patch(
        f"/pickup-requests/{pickup}", json={"report_time": at(DAY, 9).isoformat()}
    )
    assert response.status_code == 422
    assert (response.json()["code"], response.json()["pickup_request_ids"]) == (
        "not_plannable",
        [str(pickup)],
    )
    assert report_time(pickup) == at(DAY, 5)


@pytest.mark.parametrize("path", ["/pickup-requests", "/vehicles"])
def test_an_unknown_id_is_404(client, world, path):
    body = (
        {"report_time": NOW.isoformat()} if path == "/pickup-requests" else {"status": "available"}
    )
    response = client.patch(f"{path}/{uuid4()}", json=body)
    assert (response.status_code, response.json()["code"]) == (404, "not_found")


def test_a_vehicle_set_broken_down(client, world):
    van = world["vans"]["VA"]
    jobs = job_count()
    try:
        response = client.patch(f"/vehicles/{van}", json={"status": "broken_down"})
        assert response.status_code == 200, response.text
        assert (response.json()["status"], response.json()["on_the_road"]) == ("broken_down", True)
        stored = db(
            lambda conn: conn.fetchval("select status from public.vehicles where id = $1", van)
        )
        assert stored == "broken_down"
        assert job_count() == jobs
        # Its route is left as it is: only a re-plan moves it.
        status = db(
            lambda conn: conn.fetchval(
                "select status from public.routes where id = $1", world["routes"]["road"]
            )
        )
        assert status == "active"
    finally:
        world_sql("update public.vehicles set status = 'available' where id = $1", van)
