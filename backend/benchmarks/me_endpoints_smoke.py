"""Smoke run of the driver and crew read endpoints (#52) against the live
database, with real Supabase access tokens.

Not part of the app. Windows only (it stops uvicorn with Ctrl+Break). Run
from backend/, with DATABASE_URL in backend/.env:
    python -u -m benchmarks.me_endpoints_smoke <tokens.json>

tokens.json holds the three accounts from scripts/seed_test_accounts.py
--tokens (#115): {"driver"|"crew"|"dispatcher": {"id": ..., "token": ...}}.
Tokens live an hour; keep the file out of git.

Seeds only test-<run> rows: a van for the driver, a job, a second crew
member (no account), a pickup for each crew member (the crew account's on
its existing crew_members row, which is never modified), an active route
with both stops, and an older superseded route. Deletes exactly those rows
by id in a finally block, then checks that the accounts, the crew row and
the rest of the database are as they were.
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
from app.models.schemas import CrewPickupResponse, DriverRouteResponse, RouteSummaryPage

PORT = 8052
BASE = f"http://127.0.0.1:{PORT}"
RUN = uuid4().hex[:8]
# A second crew member in Kilimani, without an account.
OTHER_CREW_POINT = "SRID=4326;POINT(36.786931 -1.289279)"


async def connect() -> asyncpg.Connection:
    return await asyncpg.connect(settings.database_url, statement_cache_size=0)


async def snapshot(accounts: dict) -> dict:
    """What must be the same after the smoke: the three accounts' profiles
    and the crew account's crew_members row (every column)."""
    conn = await connect()
    try:
        ids = [UUID(a["id"]) for a in accounts.values()]
        return {
            "profiles": [
                dict(r)
                for r in await conn.fetch(
                    "select * from public.profiles where id = any($1) order by id", ids
                )
            ],
            "crew_row": dict(
                await conn.fetchrow(
                    "select id, profile_id, name, role, created_at, "
                    "extensions.st_astext(home_location) as home_location "
                    "from public.crew_members where profile_id = $1",
                    UUID(accounts["crew"]["id"]),
                )
            ),
        }
    finally:
        await conn.close()


async def seed(accounts: dict, crew_row_id: UUID) -> dict:
    now = datetime.now(UTC)
    ids: dict = {}
    conn = await connect()
    try:
        async with conn.transaction():
            ids["vehicle"] = await conn.fetchval(
                "insert into public.vehicles (assigned_driver_id, plate_number, capacity) "
                "values ($1, $2, 14) returning id",
                UUID(accounts["driver"]["id"]),
                f"T{RUN}0",
            )
            ids["job"] = await conn.fetchval(
                "insert into public.optimization_jobs (trigger_type, status, idempotency_key) "
                "values ('scheduled', 'completed', $1) returning id",
                f"test-{RUN}-smoke",
            )
            ids["other_crew"] = await conn.fetchval(
                "insert into public.crew_members (name, role, home_location) "
                "values ($1, 'pilot', $2) returning id",
                f"test-{RUN} crew",
                OTHER_CREW_POINT,
            )
            # The crew account's pickup at its own home location (read, not changed).
            ids["crew_pickup"] = await conn.fetchval(
                "insert into public.pickup_requests "
                "(crew_member_id, pickup_location, report_time, request_type, status) "
                "select id, home_location, $2, 'rostered', 'assigned' "
                "from public.crew_members where id = $1 returning id",
                crew_row_id,
                now + timedelta(hours=3),
            )
            ids["other_pickup"] = await conn.fetchval(
                "insert into public.pickup_requests "
                "(crew_member_id, pickup_location, report_time, request_type, status) "
                "values ($1, $2, $3, 'rostered', 'assigned') returning id",
                ids["other_crew"],
                OTHER_CREW_POINT,
                now + timedelta(hours=3, minutes=15),
            )
            ids["routes"], ids["nodes"] = [], []

            async def route(status, stops):
                rid = await conn.fetchval(
                    "insert into public.routes "
                    "(vehicle_id, optimization_job_id, total_distance_km, status) "
                    "values ($1, $2, 27.3, $3) returning id",
                    ids["vehicle"],
                    ids["job"],
                    status,
                )
                ids["routes"].append(rid)
                for seq, (pickup, eta_in, superseded) in enumerate(stops, start=1):
                    ids["nodes"].append(
                        await conn.fetchval(
                            "insert into public.route_nodes (route_id, pickup_request_id, "
                            "seq_order, estimated_arrival, superseded_at) "
                            "values ($1, $2, $3, $4, $5) returning id",
                            rid,
                            pickup,
                            seq,
                            now + eta_in,
                            now if superseded else None,
                        )
                    )
                return rid

            ids["old_route"] = await route(
                "superseded", [(ids["crew_pickup"], timedelta(minutes=40), True)]
            )
            ids["route"] = await route(
                "active",
                [
                    (ids["other_pickup"], timedelta(hours=1), False),
                    (ids["crew_pickup"], timedelta(hours=1, minutes=25), False),
                ],
            )
    finally:
        await conn.close()
    return ids


async def clean(ids: dict) -> None:
    conn = await connect()
    try:
        async with conn.transaction():
            await conn.execute(
                "delete from public.route_nodes where id = any($1)", ids.get("nodes", [])
            )
            await conn.execute(
                "delete from public.routes where id = any($1)", ids.get("routes", [])
            )
            await conn.execute(
                "delete from public.optimization_jobs where id = any($1)",
                [i for i in [ids.get("job")] if i],
            )
            await conn.execute(
                "delete from public.pickup_requests where id = any($1)",
                [i for i in [ids.get("crew_pickup"), ids.get("other_pickup")] if i],
            )
            await conn.execute(
                "delete from public.crew_members where id = any($1)",
                [i for i in [ids.get("other_crew")] if i],
            )
            await conn.execute(
                "delete from public.vehicles where id = any($1)",
                [i for i in [ids.get("vehicle")] if i],
            )
    finally:
        await conn.close()


async def leftovers() -> dict:
    conn = await connect()
    try:
        return {
            "test- crew": await conn.fetchval(
                "select count(*) from public.crew_members where name like 'test-%'"
            ),
            "test- jobs": await conn.fetchval(
                "select count(*) from public.optimization_jobs where idempotency_key like 'test-%'"
            ),
            "T<run> vans": await conn.fetchval(
                "select count(*) from public.vehicles where plate_number ~ '^T[0-9a-f]{8}[0-9]$'"
            ),
            "vehicles / routes / nodes / pickups / jobs": await conn.fetchval(
                "select (select count(*) from public.vehicles)::text || ' / ' || "
                "(select count(*) from public.routes) || ' / ' || "
                "(select count(*) from public.route_nodes) || ' / ' || "
                "(select count(*) from public.pickup_requests) || ' / ' || "
                "(select count(*) from public.optimization_jobs)"
            ),
        }
    finally:
        await conn.close()


def wait_for_server(server: subprocess.Popen) -> None:
    deadline = time.monotonic() + 60
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


def get(path: str, token: str | None) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return httpx.get(f"{BASE}{path}", headers=headers, timeout=30)


def main() -> None:
    accounts = json.load(open(sys.argv[1]))
    if not settings.database_url:
        sys.exit("DATABASE_URL is not set")
    before = asyncio.run(snapshot(accounts))
    print(f"run test-{RUN}; crew row {before['crew_row']['id']} ({before['crew_row']['name']})")
    ids: dict = {}
    server = None
    failures = []

    def check(label: str, ok: bool, detail: str = "") -> None:
        print(f"  {'PASS' if ok else 'FAIL'} {label}{(': ' + detail) if detail else ''}")
        if not ok:
            failures.append(label)

    try:
        ids = asyncio.run(seed(accounts, before["crew_row"]["id"]))
        print("seeded:", {k: len(v) if isinstance(v, list) else 1 for k, v in ids.items()})
        server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--workers", "1"]
            + ["--port", str(PORT), "--no-access-log"],
            env=os.environ | {"PYTHONUNBUFFERED": "1"},
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        wait_for_server(server)
        driver, crew, dispatcher = (accounts[k]["token"] for k in ("driver", "crew", "dispatcher"))

        r = get("/drivers/me/route", driver)
        print("\nGET /drivers/me/route (driver):", r.status_code)
        print(json.dumps(r.json(), indent=2))
        route = DriverRouteResponse.model_validate(r.json()).route
        check("driver route found", r.status_code == 200 and route is not None)
        if route:
            check("it is the seeded active route", route.route_id == ids["route"])
            check(
                "live stops only, in order",
                [s.route_node_id for s in route.stops] == ids["nodes"][1:],
            )
            check(
                "zone labels from PostGIS",
                [s.zone_label for s in route.stops] == ["Kilimani, Nairobi", "Westlands, Nairobi"],
            )
            check("eta null", all(s.eta is None for s in route.stops))

        r = get("/drivers/me/routes?limit=1", driver)
        print("\nGET /drivers/me/routes?limit=1 (driver):", r.status_code)
        print(json.dumps(r.json(), indent=2))
        page = RouteSummaryPage.model_validate(r.json())
        check(
            "schedule: the one active route, last page",
            [i.route_id for i in page.items] == [ids["route"]] and page.next_cursor is None,
        )

        r = get("/crew/me/pickup", crew)
        print("\nGET /crew/me/pickup (crew):", r.status_code)
        print(json.dumps(r.json(), indent=2))
        pickup = CrewPickupResponse.model_validate(r.json()).pickup
        check(
            "crew pickup is their own",
            pickup is not None and pickup.pickup_request_id == ids["crew_pickup"],
        )
        if pickup:
            check("plate of the seeded van (020)", pickup.vehicle_plate == f"T{RUN}0")
        check(
            "no coordinate keys for crew",
            not {"lat", "lon", "location", "pickup_location"} & set(r.json()["pickup"] or {}),
        )

        print("\nrole and token checks:")
        for label, path, token, expected in [
            ("crew on driver route", "/drivers/me/route", crew, 403),
            ("crew on driver schedule", "/drivers/me/routes", crew, 403),
            ("driver on crew pickup", "/crew/me/pickup", driver, 403),
            ("dispatcher on driver route", "/drivers/me/route", dispatcher, 403),
            ("dispatcher on crew pickup", "/crew/me/pickup", dispatcher, 403),
            ("no token", "/drivers/me/route", None, 401),
            ("tampered token", "/drivers/me/route", driver[:-4] + "AAAA", 401),
        ]:
            status = get(path, token).status_code
            check(f"{label} -> {expected}", status == expected, str(status))
    finally:
        if server is not None:
            server.send_signal(signal.CTRL_BREAK_EVENT)
            server.wait(timeout=30)
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
