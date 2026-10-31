"""Smoke run of the pickup-event upload (#33) against the live database,
with real Supabase access tokens.

Not part of the app. Windows only (it stops uvicorn with Ctrl+Break). Run
from backend/, with DATABASE_URL in backend/.env:
    python -u -m benchmarks.pickup_events_smoke <tokens.json>

tokens.json holds the accounts from scripts/seed_test_accounts.py --tokens
(#115): {"driver"|"crew"|"dispatcher": {"id": ..., "token": ...}}. Keep it
out of git.

Seeds only test-<run> rows: a van for the driver and a second van with no
driver, a job, four crew members without accounts, their pickups (assigned)
and an active route with their four stops. Never touches the three
accounts' rows or the crew account's crew_members row: checks they are the
same afterwards. Deletes exactly what it seeded (and the events and the
re-plan's node), by id, in a finally block.

Live checks:
1. a confirmation: accepted, with event_id; the pickup is picked_up
2. the same batch again: duplicate, the same event_id
3. a no_show: accepted; the pickup is missed
4. a confirmation made offline, then a re-plan supersedes the stop, then
   the event syncs: accepted with stop_replanned; the pickup is picked_up
5. driver_id not the signed-in driver: rejected driver_mismatch
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

PORT = 8053
BASE = f"http://127.0.0.1:{PORT}"
RUN = uuid4().hex[:8]
POINT = "SRID=4326;POINT(36.786931 -1.289279)"  # Kilimani


async def connect() -> asyncpg.Connection:
    return await asyncpg.connect(settings.database_url, statement_cache_size=0)


async def snapshot(accounts: dict) -> dict:
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


async def seed(driver_id: UUID, now: datetime) -> dict:
    ids: dict = {"crew": [], "pickups": [], "nodes": [], "routes": [], "vehicles": []}
    conn = await connect()
    try:
        async with conn.transaction():
            for plate, driver in [(f"T{RUN}0", driver_id), (f"T{RUN}1", None)]:
                ids["vehicles"].append(
                    await conn.fetchval(
                        "insert into public.vehicles (assigned_driver_id, plate_number, capacity) "
                        "values ($1, $2, 14) returning id",
                        driver,
                        plate,
                    )
                )
            ids["job"] = await conn.fetchval(
                "insert into public.optimization_jobs (trigger_type, status, idempotency_key) "
                "values ('scheduled', 'completed', $1) returning id",
                f"test-{RUN}-smoke",
            )
            for k in range(4):
                crew = await conn.fetchval(
                    "insert into public.crew_members (name, role, home_location) "
                    "values ($1, 'cabin_crew', $2) returning id",
                    f"test-{RUN} crew {k}",
                    POINT,
                )
                ids["crew"].append(crew)
                ids["pickups"].append(
                    await conn.fetchval(
                        "insert into public.pickup_requests (crew_member_id, pickup_location, "
                        "report_time, request_type, status) "
                        "values ($1, $2, $3, 'rostered', 'assigned') returning id",
                        crew,
                        POINT,
                        now + timedelta(hours=3),
                    )
                )
            for vehicle in ids["vehicles"]:
                ids["routes"].append(
                    await conn.fetchval(
                        "insert into public.routes "
                        "(vehicle_id, optimization_job_id, total_distance_km, status, "
                        "planned_departure, planned_arrival) "
                        "values ($1, $2, 20, 'active', now(), now() + interval '2 hours') "
                        "returning id",
                        vehicle,
                        ids["job"],
                    )
                )
            for seq, pickup in enumerate(ids["pickups"], start=1):
                ids["nodes"].append(
                    await conn.fetchval(
                        "insert into public.route_nodes (route_id, pickup_request_id, "
                        "seq_order, estimated_arrival) values ($1, $2, $3, $4) returning id",
                        ids["routes"][0],
                        pickup,
                        seq,
                        now + timedelta(hours=1, minutes=seq),
                    )
                )
    finally:
        await conn.close()
    return ids


async def replan(ids: dict, at: datetime) -> None:
    """The 4th stop goes to the second van: its node is superseded, and a
    live node for the same pickup goes on the second van's route."""
    conn = await connect()
    try:
        async with conn.transaction():
            await conn.execute(
                "update public.route_nodes set superseded_at = $2 where id = $1",
                ids["nodes"][3],
                at,
            )
            ids["nodes"].append(
                await conn.fetchval(
                    "insert into public.route_nodes (route_id, pickup_request_id, seq_order, "
                    "estimated_arrival) values ($1, $2, 1, $3) returning id",
                    ids["routes"][1],
                    ids["pickups"][3],
                    at + timedelta(hours=1),
                )
            )
    finally:
        await conn.close()


async def statuses(ids: dict) -> list[str]:
    conn = await connect()
    try:
        rows = await conn.fetch(
            "select id, status from public.pickup_requests where id = any($1)", ids["pickups"]
        )
        by_id = {r["id"]: r["status"] for r in rows}
        return [by_id[p] for p in ids["pickups"]]
    finally:
        await conn.close()


async def stored_ids(ids: dict) -> list[UUID]:
    conn = await connect()
    try:
        return [
            r["id"]
            for r in await conn.fetch(
                "select id from public.pickup_events where route_node_id = any($1)", ids["nodes"]
            )
        ]
    finally:
        await conn.close()


async def clean(ids: dict) -> None:
    conn = await connect()
    try:
        async with conn.transaction():
            nodes = ids.get("nodes", [])
            await conn.execute(
                "delete from public.pickup_events where route_node_id = any($1)", nodes
            )
            await conn.execute("delete from public.route_nodes where id = any($1)", nodes)
            await conn.execute(
                "delete from public.routes where id = any($1)", ids.get("routes", [])
            )
            await conn.execute(
                "delete from public.optimization_jobs where id = any($1)",
                [i for i in [ids.get("job")] if i],
            )
            await conn.execute(
                "delete from public.pickup_requests where id = any($1)", ids.get("pickups", [])
            )
            await conn.execute(
                "delete from public.crew_members where id = any($1)", ids.get("crew", [])
            )
            await conn.execute(
                "delete from public.vehicles where id = any($1)", ids.get("vehicles", [])
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
            "vehicles / routes / nodes / pickups / events / jobs": await conn.fetchval(
                "select (select count(*) from public.vehicles)::text || ' / ' || "
                "(select count(*) from public.routes) || ' / ' || "
                "(select count(*) from public.route_nodes) || ' / ' || "
                "(select count(*) from public.pickup_requests) || ' / ' || "
                "(select count(*) from public.pickup_events) || ' / ' || "
                "(select count(*) from public.optimization_jobs)"
            ),
        }
    finally:
        await conn.close()


def wait_for_server(server: subprocess.Popen) -> None:
    deadline = time.monotonic() + 90
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
    token = accounts["driver"]["token"]
    before = asyncio.run(snapshot(accounts))
    now = datetime.now(UTC)
    print(f"run test-{RUN}")
    ids: dict = {}
    server = None
    failures = []

    def check(label: str, ok: bool, detail: object = "") -> None:
        print(f"  {'PASS' if ok else 'FAIL'} {label}{(': ' + str(detail)) if detail != '' else ''}")
        if not ok:
            failures.append(label)

    def event(node: int, **fields) -> dict:
        return {
            "idempotency_key": f"test-{RUN}-{uuid4().hex[:8]}",
            "route_node_id": str(ids["nodes"][node]),
            "driver_id": str(driver_id),
            "event_type": "pickup_confirmed",
            "occurred_at": (datetime.now(UTC) - timedelta(minutes=2)).isoformat(),
        } | fields

    def upload(events: list[dict]) -> list[dict]:
        response = httpx.post(
            f"{BASE}/drivers/me/pickup-events",
            json={"events": events},
            headers={"Authorization": f"Bearer {token}"},
            timeout=60,
        )
        print(f"\nPOST /drivers/me/pickup-events -> {response.status_code}")
        print(json.dumps(response.json(), indent=2))
        assert response.status_code == 200, response.text
        return response.json()["results"]

    try:
        ids = asyncio.run(seed(driver_id, now))
        print("seeded:", {k: (len(v) if isinstance(v, list) else 1) for k, v in ids.items()})
        server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--workers", "1"]
            + ["--port", str(PORT), "--no-access-log"],
            env=os.environ | {"PYTHONUNBUFFERED": "1"},
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        wait_for_server(server)

        # 4's confirmation happens now, offline: it syncs after the re-plan.
        offline = event(3, occurred_at=(datetime.now(UTC) - timedelta(minutes=10)).isoformat())

        print("\n1. a confirmation")
        batch = [event(0)]
        [r1] = upload(batch)
        check("accepted with an event_id", r1["status"] == "accepted" and bool(r1.get("event_id")))

        print("\n2. the same batch again")
        [r2] = upload(batch)
        check("duplicate, same event_id", r2 == {**r1, "status": "duplicate"}, r2)

        print("\n3. a no_show")
        [r3] = upload([event(1, event_type="exception", exception_type="no_show")])
        check("accepted", r3["status"] == "accepted")

        print("\n4. offline confirmation, re-plan, then sync")
        asyncio.run(replan(ids, datetime.now(UTC) - timedelta(minutes=5)))
        [r4] = upload([offline])
        check(
            "accepted with stop_replanned",
            r4["status"] == "accepted" and r4.get("stop_replanned") is True,
            r4,
        )

        print("\n5. driver_id not the signed-in driver")
        [r5] = upload([event(2, driver_id=accounts["crew"]["id"])])
        check(
            "rejected driver_mismatch",
            (r5["status"], r5.get("code")) == ("rejected", "driver_mismatch"),
            r5,
        )

        print("\nstatuses after:")
        got = asyncio.run(statuses(ids))
        print(" ", got)
        check(
            "picked_up / missed / assigned (mismatch stored nothing) / picked_up",
            got == ["picked_up", "missed", "assigned", "picked_up"],
            got,
        )
        events_stored = asyncio.run(stored_ids(ids))
        check(
            "three events stored, the accepted ones",
            sorted(map(str, events_stored))
            == sorted([r1["event_id"], r3["event_id"], r4["event_id"]]),
            len(events_stored),
        )
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
