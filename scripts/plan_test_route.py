"""
ACDOS — test routes for phone checks (#123) and the end-to-end demo (#29, #27).

Run seed_test_accounts.py first. Every mode below first seeds the same test day:

1. Two test vans, capacity 4 each:
   KDA 001T for driver@acdos.test, available;
   KDA 002T for driver2@acdos.test, broken_down: the spare. The demo brings it
   in (Mark available) when KDA 001T breaks down, so the first plan always
   lands on KDA 001T.
2. Completes the vans' active routes and cancels earlier test pickups still
   pending or assigned, so re-runs start clean.
3. Four test crew: crew@acdos.test (Westlands) and three crew without
   accounts in Kilimani, Lavington and Upper Hill.
4. One fresh pending pickup request per test crew member, reporting at JKIA
   at the next 08:30 EAT that is at least three hours away.

Then:
    (default)    runs POST /optimisation-jobs as dispatcher@acdos.test with
                 KDA 001T and prints the plan. The routes come from the
                 solver, never from this script.
    --seed-only  stops there: the dispatcher runs the optimisation in the app.
    --complete   only marks the vans' active routes completed (no seeding),
                 so the next refresh on the phone shows "No route assigned".

Environment: as seed_test_accounts.py (SUPABASE_SERVICE_ROLE_KEY,
SEED_PASSWORD, optionally SUPABASE_URL).

Usage (from the repo root):
    python scripts/plan_test_route.py [--api http://127.0.0.1:8000]
    python scripts/plan_test_route.py --seed-only
    python scripts/plan_test_route.py --complete
"""

import argparse
import os
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta, timezone

import httpx
from seed_test_accounts import (
    CREW_HOME,
    DEFAULT_URL,
    access_token,
    find_user_id,
    headers,
    upsert,
)

EAT = timezone(timedelta(hours=3))
CAPACITY = 4

# (plate, driver, status after seeding). The first van is the one planned.
VANS = [
    ("KDA 001T", "driver@acdos.test", "available"),
    ("KDA 002T", "driver2@acdos.test", "broken_down"),
]

# Crew without accounts, fixed ids so re-runs reuse them. EWKT, longitude
# first; coordinates from data/pickup_zones.csv.
EXTRA_CREW = [
    ("6a9f0c1e-1b2d-4c3e-8f4a-000000000001", "Test Crew Kilimani", "POINT(36.786931 -1.289279)"),
    ("6a9f0c1e-1b2d-4c3e-8f4a-000000000002", "Test Crew Lavington", "POINT(36.777798 -1.278937)"),
    ("6a9f0c1e-1b2d-4c3e-8f4a-000000000003", "Test Crew Upper Hill", "POINT(36.813231 -1.298356)"),
]


def select(client: httpx.Client, table: str, **filters: str) -> list[dict]:
    r = client.get(f"/rest/v1/{table}", params={"select": "*", **filters})
    r.raise_for_status()
    return r.json()


def complete_active_routes(client: httpx.Client, vehicle_ids: list[str]) -> int:
    r = client.patch(
        "/rest/v1/routes",
        params={"vehicle_id": f"in.({','.join(vehicle_ids)})", "status": "eq.active"},
        headers={"Prefer": "return=representation"},
        json={"status": "completed"},
    )
    r.raise_for_status()
    return len(r.json())


def cancel_open_pickups(client: httpx.Client, crew_ids: list[str]) -> int:
    r = client.patch(
        "/rest/v1/pickup_requests",
        params={
            "crew_member_id": f"in.({','.join(crew_ids)})",
            "status": "in.(pending,assigned)",
        },
        headers={"Prefer": "return=representation"},
        json={"status": "cancelled"},
    )
    r.raise_for_status()
    return len(r.json())


def next_report_time(now: datetime) -> datetime:
    """The next 08:30 EAT at least three hours after [now]."""
    report = now.astimezone(EAT).replace(hour=8, minute=30, second=0, microsecond=0)
    while report - now < timedelta(hours=3):
        report += timedelta(days=1)
    return report


def seed_vans(client: httpx.Client) -> list[str]:
    """The test vans' ids, in VANS order, with their drivers and statuses reset."""
    ids = []
    for plate, email, status in VANS:
        upsert(
            client,
            "vehicles",
            "plate_number",
            {
                "plate_number": plate,
                "assigned_driver_id": find_user_id(client, email),
                "capacity": CAPACITY,
                "status": status,
            },
        )
        ids.append(select(client, "vehicles", plate_number=f"eq.{plate}")[0]["id"])
        print(f"{plate}  {email:<20} {status}")
    return ids


def seed_day(client: httpx.Client, vehicle_ids: list[str]) -> tuple[list[str], datetime]:
    """Fresh pending pickups for the four test crew; returns their ids and report time."""
    crew_id = find_user_id(client, "crew@acdos.test")
    crew = select(client, "crew_members", profile_id=f"eq.{crew_id}")
    if not crew:
        sys.exit("crew@acdos.test has no crew_members row: run seed_test_accounts.py first.")
    for member_id, name, point in EXTRA_CREW:
        upsert(
            client,
            "crew_members",
            "id",
            {
                "id": member_id,
                "name": name,
                "role": "cabin_crew",
                "home_location": f"SRID=4326;{point}",
            },
        )
    members = [(crew[0]["id"], CREW_HOME)]
    members += [(member_id, f"SRID=4326;{point}") for member_id, _, point in EXTRA_CREW]

    completed = complete_active_routes(client, vehicle_ids)
    cancelled = cancel_open_pickups(client, [member_id for member_id, _ in members])
    print(f"completed {completed} earlier route(s), cancelled {cancelled} earlier pickup(s)")

    report = next_report_time(datetime.now(UTC))
    r = client.post(
        "/rest/v1/pickup_requests",
        headers={"Prefer": "return=representation"},
        json=[
            {
                "crew_member_id": member_id,
                "pickup_location": location,
                "report_time": report.isoformat(),
                "request_type": "rostered",
            }
            for member_id, location in members
        ],
    )
    if r.is_error:
        sys.exit(f"pickup_requests: insert failed ({r.status_code}): {r.text}")
    print(f"{len(members)} pending pickups, report at JKIA {report:%a %d %b %H:%M} EAT")
    return [row["id"] for row in r.json()], report


def plan(api: str, token: str, pickup_ids: list[str], vehicle_id: str) -> None:
    with httpx.Client(
        base_url=api, headers={"Authorization": f"Bearer {token}"}, timeout=30
    ) as backend:
        r = backend.post(
            "/optimisation-jobs",
            headers={"Idempotency-Key": str(uuid.uuid4())},
            json={
                "trigger_type": "scheduled",
                "pickup_request_ids": pickup_ids,
                "vehicle_ids": [vehicle_id],
            },
        )
        if r.status_code != 202:
            sys.exit(f"POST /optimisation-jobs: {r.status_code} {r.text}")
        job_id = r.json()["id"]
        print(f"job {job_id} queued")

        deadline = time.monotonic() + 180
        while True:
            job = backend.get(f"/optimisation-jobs/{job_id}").raise_for_status().json()
            if job["status"] in ("completed", "failed"):
                break
            if time.monotonic() > deadline:
                sys.exit(f"job {job_id} still {job['status']} after 3 minutes")
            time.sleep(2)

    if job["status"] == "failed":
        sys.exit(f"job {job_id} failed: {job.get('error')}")
    for route in job["routes"]:
        print(f"route for {VANS[0][0]}: {route['total_distance_km']:.1f} km")
        for node in route["nodes"]:
            at = datetime.fromisoformat(node["estimated_arrival"]).astimezone(EAT)
            print(f"  {node['seq_order']}. pickup {node['pickup_request_id']} at {at:%H:%M} EAT")
    if job["late"]:
        print(f"late: {job['late']}")
    if job["unassigned"]:
        print(f"unassigned: {job['unassigned']}")
    print("pull to refresh on the driver's Route tab")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--api", default="http://127.0.0.1:8000", help="the local backend")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--seed-only", action="store_true", help="seed, but don't plan")
    mode.add_argument("--complete", action="store_true", help="only complete the vans' routes")
    args = parser.parse_args()

    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    password = os.environ.get("SEED_PASSWORD")
    url = os.environ.get("SUPABASE_URL", DEFAULT_URL).rstrip("/")
    if not key or not password:
        sys.exit("Set SUPABASE_SERVICE_ROLE_KEY and SEED_PASSWORD (see the docstring).")

    with httpx.Client(base_url=url, headers=headers(key), timeout=30) as client:
        if args.complete:
            plates = [plate for plate, _, _ in VANS]
            quoted = ",".join(f'"{plate}"' for plate in plates)
            vans = select(client, "vehicles", plate_number=f"in.({quoted})")
            count = complete_active_routes(client, [van["id"] for van in vans])
            print(f"completed {count} active route(s) of {', '.join(plates)}")
            return

        vehicle_ids = seed_vans(client)
        pickup_ids, report = seed_day(client, vehicle_ids)
        if args.seed_only:
            print(f"dispatcher: open {report:%a %d %b} and tap Run optimisation")
            return
        token = access_token(client, "dispatcher@acdos.test", password)
        plan(args.api.rstrip("/"), token, pickup_ids, vehicle_ids[0])


if __name__ == "__main__":
    main()
