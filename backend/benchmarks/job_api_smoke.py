"""Smoke run of the optimisation job API (#51) against the live database.

Not part of the app. Windows only (it stops uvicorn with Ctrl+Break). Run
from backend/, with DATABASE_URL in backend/.env:
    python -u -m benchmarks.job_api_smoke

Starts uvicorn (--workers 1) with the default settings: the Random Forest,
the 15 s limit, vans based at JKIA. Then POSTs one job and polls it, as the
dispatcher's app would.

It never plans real data. It seeds its own crew, pickups and vans, labelled
test-<run>, and in a finally block deletes them by id along with the job,
routes, route nodes and job outcomes it made. Nothing else is touched.

The crew: 16 pickup zones, two 7-seat vans (so 2 crew cannot be carried),
report times 2 to 3.5 hours away, except the crew member farthest from JKIA,
who reports in 25 minutes and so cannot be on time.
"""

import asyncio
import csv
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import asyncpg
import httpx

from app.config import settings
from app.jobs.processes import Process

ZONES_CSV = Path(__file__).resolve().parents[2] / "data" / "pickup_zones.csv"
PORT = 8051
BASE = f"http://127.0.0.1:{PORT}"
N_CREW = 16
VANS = 2
SEATS = 7
RUN = uuid4().hex[:8]


async def connect() -> asyncpg.Connection:
    return await asyncpg.connect(settings.database_url, statement_cache_size=0)


async def seed(now: datetime) -> tuple[list, list, list]:
    with ZONES_CSV.open(newline="") as f:
        zones = list(csv.DictReader(f))[:N_CREW]
    farthest = max(range(len(zones)), key=lambda i: float(zones[i]["jkia_travel_sec"]))
    conn = await connect()
    crew, pickups, vans = [], [], []
    try:
        async with conn.transaction():
            for i, zone in enumerate(zones):
                point = f"SRID=4326;POINT({zone['lon']} {zone['lat']})"
                report = (
                    now + timedelta(minutes=25)
                    if i == farthest
                    else now + timedelta(hours=2, minutes=6 * i)
                )
                crew_id = await conn.fetchval(
                    "insert into public.crew_members (name, role, home_location) "
                    "values ($1, 'cabin_crew', $2) returning id",
                    f"test-{RUN} crew {i} ({zone['zone']})",
                    point,
                )
                crew.append(crew_id)
                pickups.append(
                    await conn.fetchval(
                        "insert into public.pickup_requests "
                        "(crew_member_id, pickup_location, report_time, request_type) "
                        "values ($1, $2, $3, 'rostered') returning id",
                        crew_id,
                        point,
                        report,
                    )
                )
            for v in range(VANS):
                vans.append(
                    await conn.fetchval(
                        "insert into public.vehicles (plate_number, capacity) "
                        "values ($1, $2) returning id",
                        f"T{RUN}{v}",
                        SEATS,
                    )
                )
    finally:
        await conn.close()
    return crew, pickups, vans


async def check_rows(job_id: str, pickups: list) -> dict:
    conn = await connect()
    try:
        live = await conn.fetch(
            "select n.pickup_request_id, r.optimization_job_id from public.route_nodes n "
            "join public.routes r on r.id = n.route_id "
            "where n.pickup_request_id = any($1) and n.superseded_at is null",
            pickups,
        )
        return {
            "job": dict(
                await conn.fetchrow(
                    "select status, error, finished_at is not null as finished "
                    "from public.optimization_jobs where id = $1",
                    job_id,
                )
            ),
            "routes": await conn.fetchval(
                "select count(*) from public.routes where optimization_job_id = $1", job_id
            ),
            "live_nodes": len(live),
            "one_live_node_per_pickup": len(live) == len({n["pickup_request_id"] for n in live}),
            "outcomes": {
                r["outcome"]: r["n"]
                for r in await conn.fetch(
                    "select outcome, count(*) as n from public.optimization_job_pickups "
                    "where optimization_job_id = $1 group by outcome",
                    job_id,
                )
            },
            "pickup_statuses": {
                r["status"]: r["n"]
                for r in await conn.fetch(
                    "select status, count(*) as n from public.pickup_requests "
                    "where id = any($1) group by status",
                    pickups,
                )
            },
        }
    finally:
        await conn.close()


async def clean(crew: list, pickups: list, vans: list) -> None:
    """Only this run's rows, by id: the job made under this run's key, its
    routes, nodes and outcomes, then the seeded pickups, crew and vans."""
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
            await conn.execute(
                "delete from public.optimization_job_pickups where optimization_job_id = any($1)",
                jobs,
            )
            await conn.execute(
                "delete from public.route_nodes where route_id in "
                "(select id from public.routes where optimization_job_id = any($1))",
                jobs,
            )
            await conn.execute(
                "delete from public.routes where optimization_job_id = any($1)", jobs
            )
            await conn.execute("delete from public.optimization_jobs where id = any($1)", jobs)
            await conn.execute("delete from public.pickup_requests where id = any($1)", pickups)
            await conn.execute("delete from public.crew_members where id = any($1)", crew)
            await conn.execute("delete from public.vehicles where id = any($1)", vans)
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


def main() -> None:
    if not settings.database_url:
        sys.exit("DATABASE_URL is not set")
    now = datetime.now(UTC)
    print(
        f"run test-{RUN}: travel model {settings.travel_model}, "
        f"limit {settings.solve_time_limit_sec} s, depot ({settings.depot_lat}, "
        f"{settings.depot_lon}), pool {settings.solver_pool_size}"
    )
    crew, pickups, vans = asyncio.run(seed(now))
    print(f"seeded {len(crew)} crew, {len(pickups)} pickups, {len(vans)} vans")
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--workers", "1", "--port", str(PORT)]
        + ["--no-access-log"],
        env=os.environ | {"PYTHONUNBUFFERED": "1"},
        # Its own process group, so Ctrl+Break can stop it gracefully below.
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    solvers: list[Process] = []
    try:
        wait_for_server(server)
        body = {
            "trigger_type": "scheduled",
            "pickup_request_ids": [str(p) for p in pickups],
            "vehicle_ids": [str(v) for v in vans],
        }
        headers = {"Idempotency-Key": f"test-{RUN}-smoke"}
        accepted = httpx.post(f"{BASE}/optimisation-jobs", json=body, headers=headers, timeout=30)
        print("POST:", accepted.status_code, accepted.json())
        job_id = accepted.json()["id"]
        retried = httpx.post(f"{BASE}/optimisation-jobs", json=body, headers=headers, timeout=30)
        print(
            "POST again, same key:", retried.status_code, "same id:", retried.json()["id"] == job_id
        )

        seen, health_while_running = [], None
        deadline = time.monotonic() + 300
        while True:
            result = httpx.get(f"{BASE}/optimisation-jobs/{job_id}", timeout=30).json()
            if not seen or seen[-1] != result["status"]:
                seen.append(result["status"])
            if result["status"] == "running" and health_while_running is None:
                # The solve is in a solver process; the API must still answer.
                health_while_running = httpx.get(f"{BASE}/health", timeout=5).status_code
            if result["status"] in ("completed", "failed"):
                break
            if time.monotonic() > deadline:
                raise RuntimeError(f"job still {result['status']}")
            time.sleep(0.5)
        print("statuses seen:", " -> ".join(seen))
        print("GET /health while running:", health_while_running)
        print("error:", result["error"])
        for route in result["routes"]:
            stops = ", ".join(
                f"{n['seq_order']}@{n['estimated_arrival'][11:16]}Z" for n in route["nodes"]
            )
            print(
                f"route {route['vehicle_id'][:8]}: {route['total_distance_km']:.1f} km, "
                f"{len(route['nodes'])} stops [{stops}]"
            )
        print("late:", [(p["pickup_request_id"][:8], p["late_sec"]) for p in result["late"]])
        print("unassigned:", [p[:8] for p in result["unassigned"]])
        print("rows:", asyncio.run(check_rows(job_id, pickups)))
        # Held open now, while they run, so their exit can be checked after.
        solvers = [Process(pid) for pid in solver_pids(server.pid)]
        print("solver processes under uvicorn:", [p.pid for p in solvers])
    finally:
        stop(server)
        asyncio.run(clean(crew, pickups, vans))
        print(f"cleaned up run test-{RUN}")
    outlived = [p.pid for p in solvers if not p.wait(timeout_sec=15)]
    print("solver processes still running 15 s after uvicorn stopped:", outlived)
    assert not outlived, f"solver processes outlived uvicorn: {outlived}"


def stop(server: subprocess.Popen) -> None:
    """Ctrl+Break to uvicorn's process group: uvicorn shuts down gracefully,
    running the app's shutdown, which stops the solver pool. terminate() on
    Windows kills it outright instead, skipping all of that."""
    server.send_signal(signal.CTRL_BREAK_EVENT)
    try:
        server.wait(timeout=30)
    except subprocess.TimeoutExpired:
        server.kill()
        server.wait()
        raise


def solver_pids(root: int) -> list[int]:
    """Solver (pool) processes anywhere under root. On Windows a venv's
    python.exe is a launcher, so uvicorn itself is a child of root and its
    solver processes are grandchildren."""
    listing = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_Process | ForEach-Object "
            '{ "$($_.ProcessId)`t$($_.ParentProcessId)`t$($_.CommandLine)" }',
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    rows = [line.split("\t", 2) for line in listing.splitlines() if line.count("\t") >= 2]
    children: dict[int, list[tuple[int, str]]] = {}
    for pid, parent, command in rows:
        children.setdefault(int(parent), []).append((int(pid), command))
    found, todo = [], [root]
    while todo:
        for pid, command in children.get(todo.pop(), []):
            todo.append(pid)
            if "spawn_main" in command:
                found.append(pid)
    return found


if __name__ == "__main__":
    main()
