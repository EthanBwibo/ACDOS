"""
ACDOS — a real solver-planned route for the test driver, for phone checks (#123).

Run seed_test_accounts.py first. Then, with the backend running locally:

1. Gives driver@acdos.test a test vehicle (KDA 001T, capacity 4).
2. Makes sure there are four test crew: crew@acdos.test (Westlands) and three
   crew without accounts in Kilimani, Lavington and Upper Hill.
3. Completes the test vehicle's active route, if any, so the new plan
   doesn't sit next to an old one.
4. Creates one fresh pending pickup request per test crew member, reporting
   at JKIA at the next 08:30 EAT that is at least three hours away.
5. Runs POST /optimisation-jobs as dispatcher@acdos.test and waits for the
   plan, then prints it. The routes come from the solver, never from this
   script.

    --complete   only marks the test vehicle's active route completed, so the
                 next refresh on the phone shows "No route assigned"

Environment: as seed_test_accounts.py (SUPABASE_SERVICE_ROLE_KEY,
SEED_PASSWORD, optionally SUPABASE_URL).

Usage (from the repo root):
    python scripts/plan_test_route.py [--api http://127.0.0.1:8000]
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
PLATE = "KDA 001T"
CAPACITY = 4

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


def complete_active_routes(client: httpx.Client, vehicle_id: str) -> int:
    r = client.patch(
        "/rest/v1/routes",
        params={"vehicle_id": f"eq.{vehicle_id}", "status": "eq.active"},
        headers={"Prefer": "return=representation"},
        json={"status": "completed"},
    )
    r.raise_for_status()
    return len(r.json())


def next_report_time(now: datetime) -> datetime:
    """The next 08:30 EAT at least three hours after [now]."""
    report = now.astimezone(EAT).replace(hour=8, minute=30, second=0, microsecond=0)
    while report - now < timedelta(hours=3):
        report += timedelta(days=1)
    return report


def plan(client: httpx.Client, api: str, password: str, vehicle_id: str) -> None:
    driver_id = find_user_id(client, "driver@acdos.test")
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

    completed = complete_active_routes(client, vehicle_id)
    if completed:
        print(f"completed {completed} earlier active route(s) of {PLATE}")

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
    pickup_ids = [row["id"] for row in r.json()]
    print(f"{len(pickup_ids)} pickup requests, report at JKIA {report:%Y-%m-%d %H:%M} EAT")

    token = access_token(client, "dispatcher@acdos.test", password)
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
        print(f"route for {PLATE}: {route['total_distance_km']:.1f} km")
        for node in route["nodes"]:
            at = datetime.fromisoformat(node["estimated_arrival"]).astimezone(EAT)
            print(f"  {node['seq_order']}. pickup {node['pickup_request_id']} at {at:%H:%M} EAT")
    if job["late"]:
        print(f"late: {job['late']}")
    if job["unassigned"]:
        print(f"unassigned: {job['unassigned']}")
    print(f"driver {driver_id}: pull to refresh on the Route tab")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--api", default="http://127.0.0.1:8000", help="the local backend")
    parser.add_argument(
        "--complete", action="store_true", help="only complete the active test route"
    )
    args = parser.parse_args()

    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    password = os.environ.get("SEED_PASSWORD")
    url = os.environ.get("SUPABASE_URL", DEFAULT_URL).rstrip("/")
    if not key or not password:
        sys.exit("Set SUPABASE_SERVICE_ROLE_KEY and SEED_PASSWORD (see the docstring).")

    with httpx.Client(base_url=url, headers=headers(key), timeout=30) as client:
        driver_id = find_user_id(client, "driver@acdos.test")
        upsert(
            client,
            "vehicles",
            "plate_number",
            {
                "plate_number": PLATE,
                "assigned_driver_id": driver_id,
                "capacity": CAPACITY,
                "status": "available",
            },
        )
        vehicle_id = select(client, "vehicles", plate_number=f"eq.{PLATE}")[0]["id"]

        if args.complete:
            count = complete_active_routes(client, vehicle_id)
            print(f"completed {count} active route(s) of {PLATE}")
        else:
            plan(client, args.api.rstrip("/"), password, vehicle_id)


if __name__ == "__main__":
    main()
