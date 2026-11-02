"""Smoke run of re-planning after a disruption (#113) against the live
database, with real Supabase access tokens, through the running server.

Not part of the app. Windows only (it stops uvicorn with Ctrl+Break). Run
from backend/, with DATABASE_URL in backend/.env:
    python -u -m benchmarks.replan_smoke <tokens.json>

tokens.json holds the accounts from scripts/seed_test_accounts.py --tokens
(#115): {"driver"|"crew"|"dispatcher": {"id": ..., "token": ...}}. Keep it
out of git.

Starts uvicorn (--workers 1) with the default settings: the Random Forest,
the 15 s limit, vans based at JKIA, a 30 minute return grace.

Seeds only test-<run> rows: four vans (VA driven by the driver account, VB,
VC and VD with no driver), a seed job, nine crew members without accounts
and their pickups, and three routes:
- R1, VC over q1: left the depot 5 minutes ago, stop 1 in 15 minutes;
- R2, VA over s1 s2 s3: leaves in 2 hours;
- R4, VA over b1 b2 b3: left 20 minutes ago, b1 due now.
q2 is pending. Never touches the three accounts' rows or the crew account's
crew_members row: checks they are the same afterwards. Deletes exactly what
it seeded and what its jobs wrote, by id, in a finally block.

Live checks:
1. VC is past planned_departure but before stop 1: a job with VC gets 409
   vehicles_on_departed_routes, and one over q1 gets 409 departed_routes.
2. s1's report time moves +60 min; a flight_delay re-plan of s1 alone with
   VD re-plans all of R2 onto VD, and R2 is superseded.
3. The driver confirmed s3 offline before that re-plan, on R2's stop; it
   syncs: accepted with stop_replanned, and 025 takes s3 off VD's route.
4. The breakdown demo: the driver confirms b1 through the API, VA is set
   broken_down, a flight_delay re-plan of b2 is still refused, and a
   vehicle_breakdown re-plan with VB takes b2 and b3 with new ETAs; b1 keeps
   its node on R4 and stays picked_up.
"""

import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import asyncpg
import httpx

from app.config import settings
from benchmarks.pickup_events_smoke import leftovers, snapshot

PORT = 8054
BASE = f"http://127.0.0.1:{PORT}"
RUN = uuid4().hex[:8]
# Nairobi pickups: q1 q2, s1 s2 s3, b1 b2 b3 (lat, lon).
PLACES = {
    "q1": (-1.2675, 36.8120),
    "q2": (-1.2789, 36.7778),
    "s1": (-1.2921, 36.8219),
    "s2": (-1.3100, 36.8500),
    "s3": (-1.2200, 36.8900),
    "b1": (-1.3300, 36.7600),
    "b2": (-1.2500, 36.7400),
    "b3": (-1.3000, 36.7900),
}


async def connect() -> asyncpg.Connection:
    return await asyncpg.connect(settings.database_url, statement_cache_size=0)


async def seed(driver_id: UUID, now: datetime) -> dict:
    ids: dict = {"vans": {}, "pickups": {}, "crew": [], "nodes": {}, "routes": {}}
    conn = await connect()
    try:
        async with conn.transaction():
            for van in ["VA", "VB", "VC", "VD"]:
                ids["vans"][van] = await conn.fetchval(
                    "insert into public.vehicles (assigned_driver_id, plate_number, capacity) "
                    "values ($1, $2, 7) returning id",
                    driver_id if van == "VA" else None,
                    f"T{RUN}{van}",
                )
            ids["job"] = await conn.fetchval(
                "insert into public.optimization_jobs (trigger_type, status, idempotency_key) "
                "values ('scheduled', 'completed', $1) returning id",
                f"test-{RUN}-seed",
            )
            for name, (lat, lon) in PLACES.items():
                point = f"SRID=4326;POINT({lon} {lat})"
                crew = await conn.fetchval(
                    "insert into public.crew_members (name, role, home_location) "
                    "values ($1, 'cabin_crew', $2) returning id",
                    f"test-{RUN} crew {name}",
                    point,
                )
                ids["crew"].append(crew)
                report = now + (timedelta(minutes=90) if name[0] == "b" else timedelta(hours=3))
                ids["pickups"][name] = await conn.fetchval(
                    "insert into public.pickup_requests "
                    "(crew_member_id, pickup_location, report_time, request_type) "
                    "values ($1, $2, $3, 'rostered') returning id",
                    crew,
                    point,
                    report,
                )

            async def route(name, van, stops, departs, first_stop, arrives):
                rid = await conn.fetchval(
                    "insert into public.routes (vehicle_id, optimization_job_id, "
                    "total_distance_km, status, planned_departure, planned_arrival) "
                    "values ($1, $2, 20, 'active', $3, $4) returning id",
                    ids["vans"][van],
                    ids["job"],
                    now + departs,
                    now + arrives,
                )
                ids["routes"][name] = rid
                for seq, stop in enumerate(stops, start=1):
                    ids["nodes"][stop] = await conn.fetchval(
                        "insert into public.route_nodes (route_id, pickup_request_id, "
                        "seq_order, estimated_arrival) values ($1, $2, $3, $4) returning id",
                        rid,
                        ids["pickups"][stop],
                        seq,
                        now + first_stop + timedelta(minutes=10 * (seq - 1)),
                    )
                await conn.execute(
                    "update public.pickup_requests set status = 'assigned' "
                    "where id = any($1::uuid[])",
                    [ids["pickups"][s] for s in stops],
                )

            m = timedelta(minutes=1)
            await route("R1", "VC", ["q1"], -5 * m, 15 * m, 60 * m)
            await route("R2", "VA", ["s1", "s2", "s3"], 120 * m, 140 * m, 200 * m)
            await route("R4", "VA", ["b1", "b2", "b3"], -20 * m, 0 * m, 60 * m)
    finally:
        await conn.close()
    return ids


async def fetch(query: str, *args):
    conn = await connect()
    try:
        return await conn.fetch(query, *args)
    finally:
        await conn.close()


async def execute(query: str, *args) -> None:
    conn = await connect()
    try:
        await conn.execute(query, *args)
    finally:
        await conn.close()


async def pickup_state(pickup: UUID) -> dict:
    """The pickup's status and its live node (node, route, job, van, ETA)."""
    rows = await fetch(
        """
        select p.status, n.id as node, n.route_id, r.optimization_job_id as job,
            r.vehicle_id, n.estimated_arrival
        from public.pickup_requests p
        left join public.route_nodes n
            on n.pickup_request_id = p.id and n.superseded_at is null
        left join public.routes r on r.id = n.route_id
        where p.id = $1
        """,
        pickup,
    )
    assert len(rows) == 1, f"{pickup} has {len(rows)} live nodes"
    return dict(rows[0])


async def route_status(route: UUID) -> str:
    return (await fetch("select status from public.routes where id = $1", route))[0]["status"]


async def clean(ids: dict) -> None:
    conn = await connect()
    try:
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
            nodes = [
                r["id"]
                for r in await conn.fetch(
                    "select id from public.route_nodes where route_id = any($1)", routes
                )
            ]
            await conn.execute(
                "delete from public.pickup_events where route_node_id = any($1)", nodes
            )
            await conn.execute("delete from public.route_nodes where id = any($1)", nodes)
            await conn.execute("delete from public.routes where id = any($1)", routes)
            await conn.execute(
                "delete from public.optimization_job_pickups where optimization_job_id = any($1)",
                jobs,
            )
            await conn.execute("delete from public.optimization_jobs where id = any($1)", jobs)
            await conn.execute(
                "delete from public.pickup_requests where id = any($1)",
                list(ids.get("pickups", {}).values()),
            )
            await conn.execute(
                "delete from public.crew_members where id = any($1)", ids.get("crew", [])
            )
            await conn.execute(
                "delete from public.vehicles where id = any($1)",
                list(ids.get("vans", {}).values()),
            )
    finally:
        await conn.close()


def wait_for_server(server: subprocess.Popen) -> None:
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if server.poll() is not None:
            raise RuntimeError(f"uvicorn exited with {server.returncode}")
        try:
            if httpx.get(f"{BASE}/health", timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise RuntimeError("uvicorn did not start")


def main() -> None:
    accounts = json.load(open(sys.argv[1]))
    driver_id = UUID(accounts["driver"]["id"])
    dispatcher = {"Authorization": f"Bearer {accounts['dispatcher']['token']}"}
    driver = {"Authorization": f"Bearer {accounts['driver']['token']}"}
    before = asyncio.run(snapshot(accounts))
    now = datetime.now(UTC)
    print(f"run test-{RUN}")
    print("before:", asyncio.run(leftovers()))
    ids: dict = {}
    server = None
    failures = []

    def check(label: str, ok: bool, detail: object = "") -> None:
        print(f"  {'PASS' if ok else 'FAIL'} {label}{(': ' + str(detail)) if detail != '' else ''}")
        if not ok:
            failures.append(label)

    def post_job(pickups: list[str], vans: list[str], trigger: str) -> httpx.Response:
        body = {
            "trigger_type": trigger,
            "pickup_request_ids": [str(ids["pickups"][p]) for p in pickups],
            "vehicle_ids": [str(ids["vans"][v]) for v in vans],
        }
        response = httpx.post(
            f"{BASE}/optimisation-jobs",
            json=body,
            headers=dispatcher | {"Idempotency-Key": f"test-{RUN}-{uuid4().hex[:8]}"},
            timeout=60,
        )
        print(f"\nPOST /optimisation-jobs {trigger} {pickups} {vans} -> {response.status_code}")
        print(json.dumps(response.json(), indent=2))
        return response

    def wait_for_job(job_id: str) -> dict:
        deadline = time.monotonic() + 180
        while True:
            body = httpx.get(f"{BASE}/optimisation-jobs/{job_id}", headers=dispatcher).json()
            if body["status"] in ("completed", "failed"):
                print(f"GET /optimisation-jobs/{job_id} -> {body['status']}")
                print(json.dumps(body, indent=2))
                return body
            assert time.monotonic() < deadline, f"job {job_id} still {body['status']}"
            time.sleep(1)

    def upload(stop: str, occurred: datetime) -> dict:
        event = {
            "idempotency_key": f"test-{RUN}-{uuid4().hex[:8]}",
            "route_node_id": str(ids["nodes"][stop]),
            "driver_id": str(driver_id),
            "event_type": "pickup_confirmed",
            "occurred_at": occurred.isoformat(),
        }
        response = httpx.post(
            f"{BASE}/drivers/me/pickup-events",
            json={"events": [event]},
            headers=driver,
            timeout=60,
        )
        print(f"\nPOST /drivers/me/pickup-events ({stop}) -> {response.status_code}")
        print(json.dumps(response.json(), indent=2))
        assert response.status_code == 200, response.text
        return response.json()["results"][0]

    def names(result: dict) -> set[str]:
        by_id = {str(v): k for k, v in ids["pickups"].items()}
        planned = {n["pickup_request_id"] for r in result["routes"] for n in r["nodes"]}
        return {by_id[p] for p in planned | set(result["unassigned"])}

    def state(name: str) -> dict:
        return asyncio.run(pickup_state(ids["pickups"][name]))

    try:
        ids = asyncio.run(seed(driver_id, now))
        print("seeded:", {k: (len(v) if isinstance(v, dict | list) else 1) for k, v in ids.items()})
        server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--workers", "1"]
            + ["--port", str(PORT), "--no-access-log"],
            env=os.environ | {"PYTHONUNBUFFERED": "1"},
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        wait_for_server(server)

        print("\n1. VC past planned_departure, before stop 1")
        r = post_job(["q2"], ["VC"], "flight_delay")
        check(
            "409 vehicles_on_departed_routes with VC",
            (r.status_code, r.json().get("code"), r.json().get("vehicle_ids"))
            == (409, "vehicles_on_departed_routes", [str(ids["vans"]["VC"])]),
        )
        r = post_job(["q1"], ["VB"], "flight_delay")
        check(
            "409 departed_routes with q1",
            (r.status_code, r.json().get("code"), r.json().get("pickup_request_ids"))
            == (409, "departed_routes", [str(ids["pickups"]["q1"])]),
        )

        print("\n2. a re-plan of one pickup on a live route")
        # s3's confirmation happens now, offline: it syncs after the re-plan.
        offline = datetime.now(UTC) - timedelta(minutes=1)
        asyncio.run(
            execute(
                "update public.pickup_requests set report_time = report_time + interval "
                "'60 minutes' where id = $1",
                ids["pickups"]["s1"],
            )
        )
        r = post_job(["s1"], ["VD"], "flight_delay")
        check("202, no 409", r.status_code == 202, r.status_code)
        result = wait_for_job(r.json()["id"])
        check("job completed", result["status"] == "completed", result.get("error"))
        check("the whole route re-planned", names(result) == {"s1", "s2", "s3"}, names(result))
        check(
            "onto VD",
            {r["vehicle_id"] for r in result["routes"]} == {str(ids["vans"]["VD"])},
        )
        check("R2 superseded", asyncio.run(route_status(ids["routes"]["R2"])) == "superseded")
        for s in ["s1", "s2", "s3"]:
            got = state(s)
            check(
                f"{s} assigned, live node in the new job",
                (got["status"], str(got["job"])) == ("assigned", result["id"]),
                got["status"],
            )
        new_route = state("s1")["route_id"]

        print("\n3. s3's offline confirmation on R2 syncs")
        r3 = upload("s3", offline)
        check(
            "accepted with stop_replanned",
            r3["status"] == "accepted" and r3.get("stop_replanned") is True,
            r3,
        )
        got = state("s3")
        check(
            "025: s3 has no live node, picked_up",
            (got["node"], got["status"]) == (None, "picked_up"),
            got,
        )
        check(
            "VD's route still runs with s1 and s2",
            asyncio.run(route_status(new_route)) == "active"
            and state("s2")["route_id"] == new_route,
        )

        print("\n4. the breakdown demo")
        old_eta = {b: state(b)["estimated_arrival"] for b in ["b2", "b3"]}
        r4 = upload("b1", datetime.now(UTC) - timedelta(minutes=1))
        check("b1 collected", r4["status"] == "accepted" and not r4.get("stop_replanned"), r4)
        asyncio.run(
            execute(
                "update public.vehicles set status = 'broken_down' where id = $1",
                ids["vans"]["VA"],
            )
        )
        r = post_job(["b2"], ["VB"], "flight_delay")
        check(
            "flight_delay still refused: 409 departed_routes",
            (r.status_code, r.json().get("code")) == (409, "departed_routes"),
        )
        r = post_job(["b2"], ["VB"], "vehicle_breakdown")
        check("vehicle_breakdown accepted", r.status_code == 202, r.status_code)
        result = wait_for_job(r.json()["id"])
        check("job completed", result["status"] == "completed", result.get("error"))
        check("takes b2 and b3", names(result) == {"b2", "b3"}, names(result))
        check(
            "onto VB",
            {r["vehicle_id"] for r in result["routes"]} == {str(ids["vans"]["VB"])},
        )
        for b in ["b2", "b3"]:
            got = state(b)
            print(f"  {b}: ETA {old_eta[b]:%H:%M:%S} on VA -> {got['estimated_arrival']:%H:%M:%S}")
            check(
                f"{b} on VB in the new job with a new ETA",
                str(got["job"]) == result["id"]
                and got["vehicle_id"] == ids["vans"]["VB"]
                and got["estimated_arrival"] != old_eta[b],
            )
        got = state("b1")
        check(
            "b1 keeps its node on R4, picked_up",
            (got["node"], got["status"]) == (ids["nodes"]["b1"], "picked_up"),
            got["status"],
        )
        check("R4 still active", asyncio.run(route_status(ids["routes"]["R4"])) == "active")
    finally:
        if server is not None:
            server.send_signal(signal.CTRL_BREAK_EVENT)
            server.wait(timeout=30)
        if ids:
            asyncio.run(clean(ids))
        print(f"\ncleaned up run test-{RUN}")
        after = asyncio.run(snapshot(accounts))
        print("accounts and crew row unchanged:", after == before)
        if after != before:
            failures.append("accounts or crew row changed")
        print("leftovers:", asyncio.run(leftovers()))
    print("\nFAILED: " + ", ".join(failures) if failures else "\nall checks passed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
