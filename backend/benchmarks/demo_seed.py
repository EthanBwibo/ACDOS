"""
ACDOS — the demo morning for the defence (docs/demo_runbook.md).

    seed    one realistic morning, for tomorrow (Nairobi time) unless --date:
            3 vans of 14 seats, each with its own driver account
            (driver-101a@, driver-102a@, driver-103a@acdos.test),
            13 crew without accounts across 7 of the 28 pickup zones, and
            one pending pickup each, reporting at JKIA between 05:00 and
            07:30 EAT; plus one pickup for crew@acdos.test (Westlands), so
            the crew phone has something to show. Takes the test vans
            (TEST_VANS) out of planning, whatever their status: each becomes
            unavailable, so the dispatcher's van picker cannot offer it and
            the hub's Alerts cannot list it as broken down (#198). Their
            statuses before are recorded in HELD_FILE. Runs reset first, in
            the same transaction, so seeding twice gives the same rows.
    reset   deletes every demo row and what hangs off it: the optimisation
            jobs that planned demo pickups or vans, their job pickups,
            routes, route nodes, pickup events and trip records, and the
            demo pickups' notices and the demo crew's messages. Puts each
            test van back to its status recorded in HELD_FILE.

Demo rows are tagged: vans' plates and crew names start with "demo-". The
pickups carry no name, so they are the demo crew's pickups plus crew@'s demo
pickup, whose id is fixed. Every demo row has a fixed id (uuid5 of its name),
and reset deletes by those ids and the tag only. Non-demo rows are never
written, with one exception: the test vans' status, as above. The test
accounts, their profiles, crew@'s crew record and the pickups of
plan_test_route.py stay as they are.

The test vans' earlier statuses live in a file, HELD_FILE (gitignored), not
the database: no column holds them, and demo tooling gets no migration.
Reset restores only a test van that is still unavailable, so one the
dispatcher brought back during the demo stays as they left it, and deletes
the file once its transaction commits. With no file (seeded by an older
version, or on another laptop), reset falls back to that version's rule:
unavailable test vans become available. 'unavailable' is used by nothing
else (migration 030), so a held van is always the seed's. A job that planned
demo and non-demo rows together cannot be removed by id without touching
non-demo rows, so reset then stops and deletes nothing.

Runs as the database owner from DATABASE_URL (backend/.env, as the app),
which bypasses RLS like the service role. Run seed_test_accounts.py first:
seed looks up the three van drivers and crew@ by email in auth.users,
and stops if one is missing. Reset leaves the accounts as they are.

Usage (from backend/):
    python -m benchmarks.demo_seed seed [--date 2026-11-25]
    python -m benchmarks.demo_seed reset
"""

import argparse
import asyncio
import json
import math
import sys
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from uuid import UUID

import asyncpg

EAT = timezone(timedelta(hours=3))
TAG = "demo-"
CAPACITY = 14
CREW_EMAIL = "crew@acdos.test"

# Fixed ids: uuid5 of each row's name in this namespace (itself uuid5 of a
# fixed string), so a re-seed reuses them and reset can find them.
NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/EthanBwibo/ACDOS/demo_seed")


def demo_id(name: str) -> UUID:
    return uuid.uuid5(NAMESPACE, name)


# (plate, driver account). One account per van: the GA's plan is time-limited,
# so which van gets which stops varies between runs, and every van's route
# needs a phone that can show it.
VAN_DRIVERS = [
    ("demo-KDH 101A", "driver-101a@acdos.test"),
    ("demo-KDH 102A", "driver-102a@acdos.test"),
    ("demo-KDH 103A", "driver-103a@acdos.test"),
]
VANS = [plate for plate, _ in VAN_DRIVERS]
DRIVER_EMAILS = [email for _, email in VAN_DRIVERS]

# plan_test_route.py's vans: out of planning during the demo (#198).
TEST_VANS = ["KDA 001T", "KDA 002T"]
# Each held test van's status before the seed, {plate: status}, for reset.
HELD_FILE = Path(__file__).resolve().parents[1] / ".demo_test_vans.json"

# (name, zone label, metres east and north of the zone's point, report time
# at JKIA in EAT). Homes sit a few hundred metres off the zone point, so two
# crew in a zone are not the same stop.
CREW = [
    ("demo-Achieng Otieno", "Westlands, Nairobi", 250, -150, "05:00"),
    ("demo-Brian Kiprotich", "Westlands, Nairobi", -300, 200, "05:30"),
    ("demo-Wanjiru Kamau", "Kilimani, Nairobi", 150, 300, "05:15"),
    ("demo-David Mwangi", "Kilimani, Nairobi", -200, -250, "06:00"),
    ("demo-Faith Njeri", "Lavington, Nairobi", 200, -100, "05:45"),
    ("demo-Kevin Ochieng", "Karen, Nairobi", 350, 200, "06:15"),
    ("demo-Mercy Wambui", "Karen, Nairobi", -250, -300, "07:00"),
    ("demo-Peter Mutua", "South C, Nairobi", 200, 150, "06:30"),
    ("demo-Grace Akinyi", "South C, Nairobi", -150, -200, "07:15"),
    ("demo-Samuel Kariuki", "Embakasi, Nairobi", 300, -150, "06:45"),
    ("demo-Lucy Chebet", "Embakasi, Nairobi", -250, 250, "07:30"),
    ("demo-James Omondi", "Kasarani, Nairobi", 200, 300, "05:30"),
    ("demo-Esther Moraa", "Kasarani, Nairobi", -300, -200, "06:30"),
]

# crew@acdos.test's demo pickup: at its crew record's home (Westlands).
CREW_ACCOUNT_PICKUP = ("demo-pickup crew@acdos.test", "06:15")

CREW_ROLE = "cabin_crew"


class MixedDemoData(Exception):
    """A job planned demo and non-demo rows together: reset stops."""


@dataclass
class DemoRows:
    vans: list[UUID]
    crew: list[UUID]
    pickups: list[UUID]


def fixed_rows() -> DemoRows:
    crew = [demo_id(name) for name, *_ in CREW]
    return DemoRows(
        vans=[demo_id(plate) for plate in VANS],
        crew=crew,
        pickups=[demo_id(f"pickup {c}") for c in crew] + [demo_id(CREW_ACCOUNT_PICKUP[0])],
    )


def offset(lat: float, lon: float, east_m: float, north_m: float) -> tuple[float, float]:
    dlat = north_m / 111_320
    dlon = east_m / (111_320 * math.cos(math.radians(lat)))
    return round(lat + dlat, 6), round(lon + dlon, 6)


def ewkt(lat: float, lon: float) -> str:
    return f"SRID=4326;POINT({lon} {lat})"


def report_at(day: date, hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime.combine(day, time(h, m), EAT)


async def demo_rows(conn: asyncpg.Connection) -> DemoRows:
    """The demo rows in the database: by fixed id or by tag."""
    fixed = fixed_rows()
    vans = await conn.fetch(
        "select id from public.vehicles where id = any($1) or plate_number like 'demo-%'",
        fixed.vans,
    )
    crew = await conn.fetch(
        "select id from public.crew_members where id = any($1) or name like 'demo-%'",
        fixed.crew,
    )
    crew_ids = [r["id"] for r in crew]
    pickups = await conn.fetch(
        "select id from public.pickup_requests where id = any($1) or crew_member_id = any($2)",
        fixed.pickups,
        crew_ids,
    )
    return DemoRows(vans=[r["id"] for r in vans], crew=crew_ids, pickups=[r["id"] for r in pickups])


async def demo_jobs(conn: asyncpg.Connection, rows: DemoRows) -> list[UUID]:
    """The optimisation jobs that planned a demo van or pickup. Raises
    MixedDemoData if one of them also planned a non-demo van or pickup."""
    jobs = [
        r["id"]
        for r in await conn.fetch(
            """
            select optimization_job_id as id from public.routes where vehicle_id = any($1)
            union
            select r.optimization_job_id from public.route_nodes n
            join public.routes r on r.id = n.route_id
            where n.pickup_request_id = any($2)
            union
            select optimization_job_id from public.optimization_job_pickups
            where pickup_request_id = any($2)
            """,
            rows.vans,
            rows.pickups,
        )
    ]
    mixed = await conn.fetch(
        """
        select optimization_job_id as id from public.routes
        where optimization_job_id = any($1) and not vehicle_id = any($2)
        union
        select r.optimization_job_id from public.route_nodes n
        join public.routes r on r.id = n.route_id
        where r.optimization_job_id = any($1) and not n.pickup_request_id = any($3)
        union
        select optimization_job_id from public.optimization_job_pickups
        where optimization_job_id = any($1) and not pickup_request_id = any($3)
        """,
        jobs,
        rows.vans,
        rows.pickups,
    )
    if mixed:
        raise MixedDemoData(
            "these optimisation jobs planned demo and non-demo rows together, so reset "
            "would have to delete non-demo rows; nothing was deleted: "
            + ", ".join(sorted(str(r["id"]) for r in mixed))
        )
    return jobs


async def _reset(conn: asyncpg.Connection) -> dict[str, int]:
    rows = await demo_rows(conn)
    jobs = await demo_jobs(conn, rows)
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

    async def delete(sql: str, *args) -> int:
        return int((await conn.execute(sql, *args)).split()[-1])

    # Children first, every delete by id.
    return {
        "trip_records": await delete(
            "delete from public.trip_records where route_node_id = any($1) or vehicle_id = any($2)",
            nodes,
            rows.vans,
        ),
        "pickup_events": await delete(
            "delete from public.pickup_events where route_node_id = any($1)", nodes
        ),
        "route_nodes": await delete("delete from public.route_nodes where id = any($1)", nodes),
        "optimization_job_pickups": await delete(
            "delete from public.optimization_job_pickups where optimization_job_id = any($1)",
            jobs,
        ),
        "routes": await delete("delete from public.routes where id = any($1)", routes),
        "optimization_jobs": await delete(
            "delete from public.optimization_jobs where id = any($1)", jobs
        ),
        "schedule_change_notices": await delete(
            "delete from public.schedule_change_notices where pickup_request_id = any($1)",
            rows.pickups,
        ),
        "crew_messages": await delete(
            "delete from public.crew_messages where crew_member_id = any($1)", rows.crew
        ),
        "pickup_requests": await delete(
            "delete from public.pickup_requests where id = any($1)", rows.pickups
        ),
        "crew_members": await delete(
            "delete from public.crew_members where id = any($1)", rows.crew
        ),
        "vehicles": await delete("delete from public.vehicles where id = any($1)", rows.vans),
    }


def read_held() -> dict[str, str] | None:
    """What the last seed recorded, or None if no seed left a record."""
    try:
        return json.loads(HELD_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


async def release_test_vans(conn: asyncpg.Connection, held: dict[str, str] | None) -> int:
    """Each test van still unavailable goes back to its recorded status (to
    available with no record). Returns how many were put back."""
    statuses = held if held is not None else dict.fromkeys(TEST_VANS, "available")
    restored = 0
    for plate, status in statuses.items():
        result = await conn.execute(
            "update public.vehicles set status = $2 "
            "where plate_number = $1 and status = 'unavailable'",
            plate,
            status,
        )
        restored += int(result.split()[-1])
    return restored


async def hold_test_vans(conn: asyncpg.Connection) -> dict[str, str]:
    """Every test van becomes unavailable. Returns each one's status before.
    One already unavailable has no earlier status to record and is left out."""
    before = await conn.fetch(
        "select plate_number, status from public.vehicles "
        "where plate_number = any($1) and status <> 'unavailable'",
        TEST_VANS,
    )
    await conn.execute(
        "update public.vehicles set status = 'unavailable' where plate_number = any($1)",
        TEST_VANS,
    )
    return {r["plate_number"]: r["status"] for r in before}


async def reset(conn: asyncpg.Connection) -> dict[str, int]:
    """Deletes every demo row and puts the test vans back, all or nothing.
    Returns the rows deleted per table, and test_vans_restored."""
    held = read_held()
    async with conn.transaction():
        counts = await _reset(conn)
        counts["test_vans_restored"] = await release_test_vans(conn, held)
    HELD_FILE.unlink(missing_ok=True)  # only once the transaction has committed
    return counts


async def account_ids(conn: asyncpg.Connection) -> tuple[dict[str, UUID], UUID]:
    """Each van driver's profile id by email, and crew@'s crew record id."""
    found = {
        r["email"]: r
        for r in await conn.fetch(
            """
            select u.email, p.id as profile_id, c.id as crew_member_id
            from auth.users u
            join public.profiles p on p.id = u.id
            left join public.crew_members c on c.profile_id = p.id
            where u.email = any($1)
            """,
            [*DRIVER_EMAILS, CREW_EMAIL],
        )
    }
    missing = [email for email in DRIVER_EMAILS if email not in found]
    crew = found.get(CREW_EMAIL)
    if crew is None or crew["crew_member_id"] is None:
        missing.append(f"{CREW_EMAIL} (with its crew record)")
    if missing:
        raise SystemExit(
            f"missing test account(s): {', '.join(missing)}. "
            "Run scripts/seed_test_accounts.py first."
        )
    return {email: found[email]["profile_id"] for email in DRIVER_EMAILS}, crew["crew_member_id"]


async def seed(conn: asyncpg.Connection, day: date) -> dict:
    """Resets, then seeds the demo morning for `day`, all in one transaction."""
    driver_ids, account_crew_id = await account_ids(conn)
    zones = {
        r["label"]: (r["lat"], r["lon"])
        for r in await conn.fetch(
            """
            select label,
                extensions.st_y(location::extensions.geometry) as lat,
                extensions.st_x(location::extensions.geometry) as lon
            from public.pickup_zones where label = any($1)
            """,
            sorted({zone for _, zone, *_ in CREW}),
        )
    }
    missing = {zone for _, zone, *_ in CREW} - zones.keys()
    if missing:
        raise SystemExit(f"pickup zones not found: {', '.join(sorted(missing))}")

    earlier = read_held()
    async with conn.transaction():
        deleted = await _reset(conn)
        # Back to their statuses before any earlier seed, then held again, so
        # the record always holds the statuses from before the first seed.
        await release_test_vans(conn, earlier)
        for plate, email in VAN_DRIVERS:
            await conn.execute(
                """
                insert into public.vehicles (id, assigned_driver_id, plate_number, capacity, status)
                values ($1, $2, $3, $4, 'available')
                """,
                demo_id(plate),
                driver_ids[email],
                plate,
                CAPACITY,
            )
        for name, zone, east, north, hhmm in CREW:
            home = ewkt(*offset(*zones[zone], east, north))
            crew_id = demo_id(name)
            await conn.execute(
                """
                insert into public.crew_members (id, name, role, home_location)
                values ($1, $2, $3, $4::text::extensions.geography)
                """,
                crew_id,
                name,
                CREW_ROLE,
                home,
            )
            await conn.execute(
                """
                insert into public.pickup_requests
                    (id, crew_member_id, pickup_location, report_time, request_type)
                values ($1, $2, $3::text::extensions.geography, $4, 'rostered')
                """,
                demo_id(f"pickup {crew_id}"),
                crew_id,
                home,
                report_at(day, hhmm),
            )
        await conn.execute(
            """
            insert into public.pickup_requests
                (id, crew_member_id, pickup_location, report_time, request_type)
            select $1, c.id, c.home_location, $3, 'rostered'
            from public.crew_members c where c.id = $2
            """,
            demo_id(CREW_ACCOUNT_PICKUP[0]),
            account_crew_id,
            report_at(day, CREW_ACCOUNT_PICKUP[1]),
        )
        held = await hold_test_vans(conn)
    # Written only once the transaction has committed.
    HELD_FILE.write_text(json.dumps(held, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return {
        "deleted": deleted,
        "test_vans_held": held,
        "vans": len(VANS),
        "crew": len(CREW),
        "pickups": len(CREW) + 1,
        "warnings": await warnings(conn, day, list(driver_ids.values()), account_crew_id),
    }


async def warnings(
    conn: asyncpg.Connection, day: date, driver_ids: list[UUID], account_crew_id: UUID
) -> list[str]:
    """Non-demo rows that would change the demo. Reported, never changed."""
    fixed = fixed_rows()
    day_start = datetime.combine(day, time(0), EAT)
    found = []
    vans = await conn.fetch(
        """
        select plate_number from public.vehicles
        where status not in ('broken_down', 'unavailable') and not id = any($1)
          and plate_number not like 'demo-%'
        order by plate_number
        """,
        fixed.vans,
    )
    if vans:
        found.append(
            "non-demo vans the picker still offers: "
            + ", ".join(v["plate_number"] for v in vans)
            + ". Untick them when you run the optimisation: reset cannot remove a job "
            "that mixed demo and non-demo vans."
        )
    pickups = await conn.fetchval(
        """
        select count(*) from public.pickup_requests p
        join public.crew_members c on c.id = p.crew_member_id
        where p.status = 'pending' and p.report_time >= $1 and p.report_time < $2
          and not p.id = any($3) and c.name not like 'demo-%'
        """,
        day_start,
        day_start + timedelta(days=1),
        fixed.pickups,
    )
    if pickups:
        found.append(
            f"{pickups} non-demo pending pickup(s) on {day}: Run optimisation would plan "
            "them too. Seed another day with --date, or cancel them first."
        )
    earlier = await conn.fetchval(
        """
        select count(*) from public.pickup_requests
        where crew_member_id = $1 and id <> $2 and status in ('pending', 'assigned')
          and report_time >= now() and report_time < $3
        """,
        account_crew_id,
        demo_id(CREW_ACCOUNT_PICKUP[0]),
        report_at(day, CREW_ACCOUNT_PICKUP[1]),
    )
    if earlier:
        found.append(
            f"{CREW_EMAIL} has {earlier} earlier open pickup(s): its phone shows those first."
        )
    routes = await conn.fetchval(
        """
        select count(*) from public.routes r join public.vehicles v on v.id = r.vehicle_id
        where v.assigned_driver_id = any($1) and r.status = 'active' and not v.id = any($2)
        """,
        driver_ids,
        fixed.vans,
    )
    if routes:
        found.append(
            f"the demo drivers have {routes} active route(s) on non-demo vans: a driver's "
            "phone shows the route that starts first."
        )
    return found


def tomorrow() -> date:
    return datetime.now(EAT).date() + timedelta(days=1)


async def main_async(args: argparse.Namespace) -> None:
    from app.config import settings

    if not settings.database_url:
        sys.exit("Set DATABASE_URL (backend/.env or the environment).")
    conn = await asyncpg.connect(settings.database_url, statement_cache_size=0)
    try:
        if args.command == "reset":
            try:
                deleted = await reset(conn)
            except MixedDemoData as e:
                sys.exit(f"reset: {e}")
            restored = deleted.pop("test_vans_restored")
            done = ", ".join(f"{k} {v}" for k, v in deleted.items() if v)
            print(f"reset: deleted {done}" if done else "reset: no demo rows")
            if restored:
                print(f"reset: {restored} test van(s) back to their status before the seed")
        else:
            day = args.date or tomorrow()
            try:
                summary = await seed(conn, day)
            except MixedDemoData as e:
                sys.exit(f"seed: {e}")
            print(
                f"seed: {summary['vans']} vans of {CAPACITY} seats ("
                + ", ".join(f"{plate} for {email}" for plate, email in VAN_DRIVERS)
                + f"), {summary['crew']} demo crew, {summary['pickups']} pickups "
                f"reporting on {day} 05:00-07:30 EAT (incl. {CREW_EMAIL} at "
                f"{CREW_ACCOUNT_PICKUP[1]})"
            )
            if summary["test_vans_held"]:
                held = ", ".join(f"{p} (was {s})" for p, s in summary["test_vans_held"].items())
                print(f"seed: unavailable until reset: {held}")
            for warning in summary["warnings"]:
                print(f"warning: {warning}")
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("command", choices=["seed", "reset"])
    parser.add_argument(
        "--date", type=date.fromisoformat, help="the demo day (default: tomorrow, EAT)"
    )
    asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    main()
