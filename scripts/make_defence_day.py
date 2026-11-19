"""
ACDOS: the defence day (#252). 120 crew across the 28 pickup zones, 120
pickups in five bands weighted like Kenya Airways' departure banks, and 20
vans of 14 seats, each with its driver account.

    roster  writes the day's roster CSV for the live import, in the format of
            docs/roster_import.md (#246): most rows with no pickup_location
            (picked up from home), 4 one-off points (one as a Google Maps
            link), 1 set_home move, then 4 bad rows, so the dry run shows
            rejections. Default docs/defence_roster.csv.
    seed    writes the same day straight to the database: the fallback if the
            live import fails. Runs reset first, in the same transaction.
            --crew-only  only the crew and vans, without the day's pickups:
                         what the live import needs, since most rows give
                         no location and use the crew member's home
            --plan       then plans each band, as plan does
    plan    plans each band of the day on the deployed API, signed in as
            dispatcher@acdos.test: one job per band with that band's vans
            (VAN_GROUPS), timing each from POST to completed. Works on a
            seeded day and on an imported one.
            --whole-day  one job instead, with every pickup and van: what
                         the app's Plan tab sends with every van ticked
    reset   deletes the defence rows and what hangs off them (routes, jobs,
            events, notices, the defence crew's messages), the same way
            backend/benchmarks/demo_seed.py does: vans and crew tagged
            "defence-", and every pickup of theirs and of the 8 named crew.

Bands, report times at JKIA in Nairobi time, and their share of the pickups:

    early      04:00-06:30   35%   42 pickups   vans 001-007
    mid        08:00-10:00   20%   24 pickups   vans 008-011
    noon       11:30-13:30   15%   18 pickups   vans 012-014
    afternoon  15:00-17:30   15%   18 pickups   vans 015-017
    night      20:00-23:00   15%   18 pickups   vans 018-020

Each band has its own vans by default. With plan --reuse, every band is
planned with all 20 vans instead, in order, so a van whose earlier band's
route is in at JKIA in time is reused (van reuse across waves,
app/jobs/store.py); each band's line then says how many vans it used.

Crew: the 8 named crew of scripts/seed_test_accounts.py (with logins, their
records owned by that script and never deleted here) and 112 more, tagged
"defence-", staff numbers KQ40001 to KQ40112, 4 per zone, homes 0.3 to 2.5
km from the zone's point. The crew depend only on --seed, the pickups on
--date and --seed: the same date and seed always give the same file and rows.
9 crew (Brian and 8 more) have pickups in two bands, with at least one band
between them; 9 have none that
day. 6 pickups are standby.

Run scripts/seed_test_accounts.py first: seed looks up the 20 drivers and
the 8 named crew, and plan signs in as the dispatcher.

Environment (seed, plan, reset):
    DATABASE_URL                Postgres, as the app (or in backend/.env)
    SUPABASE_SERVICE_ROLE_KEY   plan only: to sign in (as seed_test_accounts.py)
    SEED_PASSWORD               plan only: the accounts' password

Usage (from the repo root, with the backend venv):
    python scripts/make_defence_day.py roster [--date 2026-11-20] [--out file.csv]
    python scripts/make_defence_day.py seed [--date ...] [--crew-only] [--plan]
    python scripts/make_defence_day.py plan [--date ...] [--api https://...] [--whole-day]
    python scripts/make_defence_day.py reset
"""

import argparse
import asyncio
import csv
import io
import math
import os
import random
import sys
import time as clock
import uuid
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from uuid import UUID

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "backend"))

import seed_test_accounts as accounts  # noqa: E402

# Nairobi time: a fixed offset, as in make_sample_roster.py.
EAT = timezone(timedelta(hours=3), "EAT")
TAG = "defence-"
CAPACITY = 14
DEFAULT_SEED = 252
DEFAULT_OUT = ROOT / "docs" / "defence_roster.csv"
API_URL = "https://acdos-api.azurewebsites.net"
DISPATCHER = "dispatcher@acdos.test"

# Fixed ids, uuid5 of each row's name, so a re-seed reuses them.
NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/EthanBwibo/ACDOS/defence_day")


def fixed_id(name: str) -> UUID:
    return uuid.uuid5(NAMESPACE, name)


@dataclass(frozen=True)
class Band:
    key: str
    start: time  # report times at JKIA, both ends included
    end: time
    pickups: int
    vans: int


BANDS = [
    Band("early", time(4, 0), time(6, 30), 42, 7),
    Band("mid", time(8, 0), time(10, 0), 24, 4),
    Band("noon", time(11, 30), time(13, 30), 18, 3),
    Band("afternoon", time(15, 0), time(17, 30), 18, 3),
    Band("night", time(20, 0), time(23, 0), 18, 3),
]
BAND = {b.key: b for b in BANDS}
assert tuple(BAND) == accounts.BANDS

# The vans of each band, in plate order: 001-007 early, 008-011 mid, ...
VAN_GROUPS: dict[str, list[tuple[str, str]]] = {}
_next = 0
for _band in BANDS:
    VAN_GROUPS[_band.key] = [
        (p, e) for p, e, _ in accounts.DEFENCE_VANS[_next : _next + _band.vans]
    ]
    _next += _band.vans
assert _next == len(accounts.DEFENCE_VANS)

GENERATED = 112  # crew besides the 8 named: 120 in all
DOUBLES = 8  # crew with a pickup in two bands
STANDBY = 6
ONE_OFF = 4  # pickups at a point other than home
PILOT_SHARE = 0.2

# fmt: off
FIRST = [
    "Achieng", "Adhiambo", "Akinyi", "Aisha", "Brenda", "Caroline", "Cynthia", "Diana",
    "Edwin", "Eric", "Evans", "Fatuma", "Gladys", "Hassan", "Ian", "Irene", "Jackline",
    "Kevin", "Linet", "Mercy", "Mohamed", "Nancy", "Njeri", "Omar", "Purity", "Rose",
    "Ruth", "Tabitha", "Wanjiru", "Zawadi",
]
LAST = [
    "Atieno", "Biwott", "Cheruiyot", "Gathoni", "Hussein", "Jeptoo", "Kamau", "Karanja",
    "Kemboi", "Kilonzo", "Langat", "Macharia", "Maina", "Mbugua", "Musyoka", "Mwende",
    "Nduta", "Ngugi", "Nyambura", "Ochieng", "Okoth", "Oloo", "Onyango", "Owino",
    "Ruto", "Saitoti", "Sang", "Waweru", "Were", "Yegon",
]
# fmt: on

# Rejected by the import (docs/roster_import.md): over 10 km from every zone.
NAKURU = (-0.303099, 36.080025)
PAST = date(2026, 1, 15)


@dataclass(frozen=True)
class Crew:
    staff_no: str
    name: str
    role: str
    zone: str
    lat: float  # home
    lon: float


@dataclass(frozen=True)
class Pickup:
    staff_no: str
    band: str
    report: datetime
    request_type: str = "rostered"
    point: tuple[float, float] | None = None  # None: from home
    set_home: bool = False  # the point becomes their home
    as_link: bool = False  # written as a Google Maps link, not "lat, lon"


def offset(lat: float, lon: float, east_m: float, north_m: float) -> tuple[float, float]:
    """A point east_m and north_m from (lat, lon), treating the Earth as flat:
    close enough over a few km."""
    dlat = north_m / 111_320
    dlon = east_m / (111_320 * math.cos(math.radians(lat)))
    return round(lat + dlat, 6), round(lon + dlon, 6)


def near(rng: random.Random, lat: float, lon: float, low_m: float, high_m: float):
    distance = rng.uniform(low_m, high_m)
    bearing = rng.uniform(0, 2 * math.pi)
    return offset(lat, lon, distance * math.sin(bearing), distance * math.cos(bearing))


def build_crew(seed: int = DEFAULT_SEED) -> list[Crew]:
    """The 8 named crew, then 112 tagged ones, 4 per zone."""
    zones = accounts.zone_points()
    named = [
        Crew(c.staff_no, c.name, c.role, c.zone, *accounts.home_of(c, zones))
        for c in accounts.NAMED_CREW
    ]
    rng = random.Random(f"crew/{seed}")
    taken = {c.name for c in named}
    names = rng.sample(
        [f"{f} {s}" for f in FIRST for s in LAST if f"{f} {s}" not in taken], GENERATED
    )
    zone_labels = sorted(zones)
    generated = []
    for i, name in enumerate(names):
        zone = zone_labels[i % len(zone_labels)]
        role = "pilot" if rng.random() < PILOT_SHARE else "cabin_crew"
        lat, lon = near(rng, *zones[zone], 300, 2500)
        generated.append(Crew(f"KQ{40001 + i}", TAG + name, role, zone, lat, lon))
    return named + generated


def report_in(rng: random.Random, day: date, band: Band) -> datetime:
    """A report time in the band, on a 5-minute mark."""
    start = band.start.hour * 60 + band.start.minute
    end = band.end.hour * 60 + band.end.minute
    minutes = start + 5 * rng.randrange((end - start) // 5 + 1)
    return datetime.combine(day, time(minutes // 60, minutes % 60), EAT)


def build_pickups(day: date, seed: int = DEFAULT_SEED) -> list[Pickup]:
    """The day's 120 pickups, sorted by report time."""
    crew = build_crew(seed)
    zones = accounts.zone_points()
    rng = random.Random(f"pickups/{day.isoformat()}/{seed}")
    order = [b.key for b in BANDS]

    named = [(c.staff_no, band) for c in accounts.NAMED_CREW for band in c.bands]
    left = {b.key: b.pickups - sum(1 for _, k in named if k == b.key) for b in BANDS}
    slots = [k for k in order for _ in range(left[k])]
    rng.shuffle(slots)

    generated = [c.staff_no for c in crew if c.name.startswith(TAG)]
    people = rng.sample(generated, len(generated))
    singles = len(slots) - DOUBLES
    assigned = list(zip(people[:singles], slots[:singles], strict=True))
    # Each of the last slots goes to a crew member who has one pickup so far,
    # in a band at least one band away from it.
    first_band = dict(assigned)
    doubled: set[str] = set()
    for band in slots[singles:]:
        who = next(
            s
            for s in people[:singles]
            if s not in doubled and abs(order.index(first_band[s]) - order.index(band)) >= 2
        )
        doubled.add(who)
        assigned.append((who, band))

    pickups = [Pickup(s, band, report_in(rng, day, BAND[band])) for s, band in named + assigned]

    # Standby, one-off points and the home move: generated crew only, so the
    # named crew's phones always show a plain rostered pickup from home.
    mine = [i for i, p in enumerate(pickups) if p.staff_no in first_band]
    picks = rng.sample(mine, STANDBY + ONE_OFF)
    # The move: a crew member with one pickup that day, so the file and the
    # seeded day agree whatever the move's report time.
    move = rng.choice([i for i in mine if i not in picks and pickups[i].staff_no not in doubled])
    by_staff = {c.staff_no: c for c in crew}

    def elsewhere(i: int) -> tuple[float, float]:
        """A point near a zone other than the crew member's home zone."""
        home_zone = by_staff[pickups[i].staff_no].zone
        zone = rng.choice([z for z in sorted(zones) if z != home_zone])
        return near(rng, *zones[zone], 300, 1500)

    for i in picks[:STANDBY]:
        pickups[i] = replace(pickups[i], request_type="standby")
    for n, i in enumerate(picks[STANDBY:]):
        pickups[i] = replace(pickups[i], point=elsewhere(i), as_link=n == 0)
    pickups[move] = replace(pickups[move], point=elsewhere(move), set_home=True)
    return sorted(pickups, key=lambda p: (p.report, p.staff_no))


def maps_link(lat: float, lon: float) -> str:
    """A Google Maps place link: the import reads the pin, !3d<lat>!4d<lon>."""
    return (
        f"https://www.google.com/maps/place/@{lat},{lon},17z/"
        f"data=!3m1!4b1!4m4!3m3!8m2!3d{lat}!4d{lon}"
    )


def build_roster(day: date, seed: int = DEFAULT_SEED) -> str:
    """The CSV text: the 120 pickups, then 4 bad rows."""
    crew = {c.staff_no: c for c in build_crew(seed)}
    pickups = build_pickups(day, seed)
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(
        (
            "staff_no",
            "name",
            "crew_role",
            "pickup_location",
            "report_time",
            "request_type",
            "set_home",
        )
    )

    def row(p: Pickup, report: str | None = None, location: str | None = None) -> tuple:
        c = crew[p.staff_no]
        if location is None:
            location = (
                ""
                if p.point is None
                else maps_link(*p.point)
                if p.as_link
                else f"{p.point[0]}, {p.point[1]}"
            )
        return (
            c.staff_no,
            c.name,
            c.role,
            location,
            report or p.report.isoformat(),
            p.request_type,
            "yes" if p.set_home else "",
        )

    for p in pickups:
        writer.writerow(row(p))
    # The bad rows, on generated crew: one per reason, as the dry run shows them.
    plain = [p for p in pickups if p.staff_no.startswith("KQ4") and p.point is None]
    first, second, third = plain[0], plain[len(plain) // 2], plain[-1]
    writer.writerow(row(first))  # duplicate_pickup: the same crew and time again
    writer.writerow(  # outside_pickup_zones: Nakuru, at a time of their own
        row(
            second,
            (second.report + timedelta(minutes=2)).isoformat(),
            f"{NAKURU[0]}, {NAKURU[1]}",
        )
    )
    writer.writerow(  # report_time_past
        row(third, datetime.combine(PAST, time(8, 0), EAT).isoformat())
    )
    writer.writerow(  # invalid_row: no UTC offset, so Nairobi time or UTC?
        row(third, third.report.replace(tzinfo=None).isoformat())
    )
    return out.getvalue()


# --- The database --------------------------------------------------------


def ewkt(lat: float, lon: float) -> str:
    return f"SRID=4326;POINT({lon} {lat})"


def fixed_vans() -> list[UUID]:
    return [fixed_id(plate) for plate, _, _ in accounts.DEFENCE_VANS]


def fixed_crew(seed: int) -> list[UUID]:
    return [fixed_id(c.staff_no) for c in build_crew(seed) if c.name.startswith(TAG)]


async def named_crew_ids(conn) -> dict[str, UUID]:
    """The 8 named crew's records, by staff number."""
    return {
        r["staff_no"]: r["id"]
        for r in await conn.fetch(
            "select staff_no, id from public.crew_members where staff_no = any($1)",
            [c.staff_no for c in accounts.NAMED_CREW],
        )
    }


async def defence_rows(conn, seed: int = DEFAULT_SEED):
    """The defence rows in the database: by fixed id or by tag, and every
    pickup of a defence crew member or a named one."""
    from benchmarks.demo_seed import DemoRows

    vans = await conn.fetch(
        "select id from public.vehicles where id = any($1) or plate_number like 'defence-%'",
        fixed_vans(),
    )
    crew = [
        r["id"]
        for r in await conn.fetch(
            "select id from public.crew_members where id = any($1) or name like 'defence-%'",
            fixed_crew(seed),
        )
    ]
    named = list((await named_crew_ids(conn)).values())
    pickups = await conn.fetch(
        "select id from public.pickup_requests where crew_member_id = any($1)",
        crew + named,
    )
    return DemoRows(vans=[r["id"] for r in vans], crew=crew, pickups=[r["id"] for r in pickups])


async def reset(conn, seed: int = DEFAULT_SEED) -> dict[str, int]:
    from benchmarks.demo_seed import delete_rows

    async with conn.transaction():
        return await delete_rows(conn, await defence_rows(conn, seed))


async def seed_day(conn, day: date, seed: int, *, crew_only: bool) -> dict:
    """Resets, then writes the crew and vans, and unless crew_only the day's
    pickups, all in one transaction."""
    from benchmarks.demo_seed import delete_rows

    emails = [e for _, e, _ in accounts.DEFENCE_VANS]
    drivers = {
        r["email"]: r["id"]
        for r in await conn.fetch(
            "select u.email, p.id from auth.users u join public.profiles p on p.id = u.id "
            "where u.email = any($1)",
            emails,
        )
    }
    named = await named_crew_ids(conn)
    missing = [e for e in emails if e not in drivers] + [
        c.email for c in accounts.NAMED_CREW if c.staff_no not in named
    ]
    if missing:
        raise SystemExit(
            f"missing account(s): {', '.join(missing)}. Run scripts/seed_test_accounts.py first."
        )

    crew = build_crew(seed)
    pickups = [] if crew_only else build_pickups(day, seed)
    async with conn.transaction():
        deleted = await delete_rows(conn, await defence_rows(conn, seed))
        for plate, email, _ in accounts.DEFENCE_VANS:
            await conn.execute(
                "insert into public.vehicles (id, assigned_driver_id, plate_number, capacity, "
                "status) values ($1, $2, $3, $4, 'available')",
                fixed_id(plate),
                drivers[email],
                plate,
                CAPACITY,
            )
        ids = dict(named)
        for c in crew:
            if not c.name.startswith(TAG):
                continue
            ids[c.staff_no] = fixed_id(c.staff_no)
            await conn.execute(
                "insert into public.crew_members (id, staff_no, name, role, home_location) "
                "values ($1, $2, $3, $4, $5::text::extensions.geography)",
                ids[c.staff_no],
                c.staff_no,
                c.name,
                c.role,
                ewkt(c.lat, c.lon),
            )
        for p in pickups:
            if p.set_home:
                await conn.execute(
                    "update public.crew_members set home_location = "
                    "$2::text::extensions.geography where id = $1",
                    ids[p.staff_no],
                    ewkt(*p.point),
                )
            # From home unless the row has its own point, as the import does.
            await conn.execute(
                """
                insert into public.pickup_requests
                    (id, crew_member_id, pickup_location, report_time, request_type)
                select $1, c.id, coalesce($3::text::extensions.geography, c.home_location),
                    $4, $5
                from public.crew_members c where c.id = $2
                """,
                fixed_id(f"pickup {p.staff_no} {p.band}"),
                ids[p.staff_no],
                ewkt(*p.point) if p.point else None,
                p.report,
                p.request_type,
            )
    return {"deleted": deleted, "crew": len(crew), "pickups": len(pickups)}


async def band_jobs(conn, day: date, seed: int) -> list[tuple[str, list[UUID], list[UUID]]]:
    """(band, pending pickups, vans) per band: the defence and named crew's
    pending pickups reporting in the band's window on the day."""
    crew = (await defence_rows(conn, seed)).crew + list((await named_crew_ids(conn)).values())
    rows = await conn.fetch(
        """
        select id, report_time from public.pickup_requests
        where crew_member_id = any($1) and status = 'pending'
          and report_time >= $2 and report_time < $3
        """,
        crew,
        datetime.combine(day, time(0), EAT),
        datetime.combine(day + timedelta(days=1), time(0), EAT),
    )
    vans = {
        r["plate_number"]: r["id"]
        for r in await conn.fetch(
            "select plate_number, id from public.vehicles where plate_number like 'defence-%'"
        )
    }
    jobs = []
    for band in BANDS:
        start = datetime.combine(day, band.start, EAT)
        end = datetime.combine(day, band.end, EAT)
        ids = [r["id"] for r in rows if start <= r["report_time"] <= end]
        jobs.append((band.key, ids, [vans[p] for p, _ in VAN_GROUPS[band.key] if p in vans]))
    return jobs


def whole_day(jobs: list[tuple[str, list[UUID], list[UUID]]]):
    """The bands' jobs as the one job the app's Plan tab sends: every pickup
    of the day, with every van ticked."""
    return [("whole-day", [p for _, ps, _ in jobs for p in ps], [v for _, _, vs in jobs for v in vs])]


def reuse_fleet(jobs: list[tuple[str, list[UUID], list[UUID]]]):
    """The bands' jobs with every van ticked in each, planned in band order,
    so vans are reused from one band to the next."""
    vans = [v for _, _, vs in jobs for v in vs]
    return [(band, pickups, vans) for band, pickups, _ in jobs]


def plan_bands(jobs, api: str) -> list[dict]:
    """One optimisation job per band on the API, one after another, each timed
    from POST to completed or failed."""
    import httpx

    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    password = os.environ.get("SEED_PASSWORD")
    if not key or not password:
        sys.exit("plan: set SUPABASE_SERVICE_ROLE_KEY and SEED_PASSWORD.")
    supabase = os.environ.get("SUPABASE_URL", accounts.DEFAULT_URL).rstrip("/")
    with httpx.Client(base_url=supabase, headers=accounts.headers(key), timeout=30) as auth:
        token = accounts.access_token(auth, DISPATCHER, password)

    results = []
    with httpx.Client(
        base_url=api.rstrip("/"),
        headers={"Authorization": f"Bearer {token}"},
        timeout=60,
    ) as client:
        for band, pickups, vans in jobs:
            if not pickups or not vans:
                print(f"plan: {band}: {len(pickups)} pickups, {len(vans)} vans; skipped")
                continue
            started = clock.monotonic()
            r = client.post(
                "/optimisation-jobs",
                headers={"Idempotency-Key": f"defence-{band}-{uuid.uuid4()}"},
                json={
                    "trigger_type": "scheduled",
                    "pickup_request_ids": [str(i) for i in pickups],
                    "vehicle_ids": [str(i) for i in vans],
                },
            )
            if r.is_error:
                sys.exit(f"plan: {band}: {r.status_code} {r.text}")
            job_id = r.json()["id"]
            while True:
                clock.sleep(1)
                job = client.get(f"/optimisation-jobs/{job_id}")
                job.raise_for_status()
                body = job.json()
                if body["status"] in ("completed", "failed"):
                    break
                if clock.monotonic() - started > 600:
                    sys.exit(f"plan: {band}: job {job_id} still {body['status']} after 10 min")
            result = {
                "band": band,
                "pickups": len(pickups),
                "vans": len(vans),
                "seconds": round(clock.monotonic() - started, 1),
                "status": body["status"],
                "routes": sum(1 for route in body["routes"] if route["nodes"]),
                "late": len(body["late"]),
                "unassigned": len(body["unassigned"]),
                "used": sorted({route["vehicle_id"] for route in body["routes"] if route["nodes"]}),
                "left_out": len(body.get("left_out", [])),
                "job": job_id,
            }
            print(
                f"plan: {band:<9} {result['pickups']:>3} pickups, {result['vans']} vans: "
                f"{result['status']} in {result['seconds']} s, {result['routes']} routes, "
                f"{result['late']} late, {result['unassigned']} unassigned, "
                f"{len(result['used'])} vans used, {result['left_out']} left out (job {job_id})"
            )
            results.append(result)
    used = {van for result in results for van in result["used"]}
    print(f"plan: {len(used)} vans used over {len(results)} job(s)")
    return results


def tomorrow() -> date:
    return datetime.now(EAT).date() + timedelta(days=1)


async def connect():
    import asyncpg

    from app.config import Settings

    url = (
        os.environ.get("DATABASE_URL") or Settings(_env_file=ROOT / "backend" / ".env").database_url
    )
    if not url:
        sys.exit("Set DATABASE_URL (or backend/.env).")
    return await asyncpg.connect(url, statement_cache_size=0)


async def main_async(args: argparse.Namespace) -> None:
    from benchmarks.demo_seed import MixedDemoData

    day = args.date or tomorrow()
    conn = await connect()
    try:
        if args.command == "reset":
            try:
                deleted = await reset(conn, args.seed)
            except MixedDemoData as e:
                sys.exit(f"reset: {e}")
            done = ", ".join(f"{k} {v}" for k, v in deleted.items() if v)
            print(f"reset: deleted {done}" if done else "reset: no defence rows")
            return
        if args.command == "seed":
            try:
                summary = await seed_day(conn, day, args.seed, crew_only=args.crew_only)
            except MixedDemoData as e:
                sys.exit(f"seed: {e}")
            print(
                f"seed: {len(accounts.DEFENCE_VANS)} vans of {CAPACITY} seats, "
                f"{summary['crew']} crew, {summary['pickups']} pickups on {day}"
            )
            if not args.plan:
                return
        jobs = await band_jobs(conn, day, args.seed)
        if args.whole_day:
            jobs = whole_day(jobs)
        elif args.reuse:
            jobs = reuse_fleet(jobs)
    finally:
        await conn.close()
    plan_bands(jobs, args.api)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("command", choices=["roster", "seed", "plan", "reset"])
    parser.add_argument("--date", type=date.fromisoformat, help="default: tomorrow, Nairobi")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="roster: the CSV")
    parser.add_argument("--crew-only", action="store_true", help="seed: no pickups")
    parser.add_argument("--plan", action="store_true", help="seed: then plan each band")
    parser.add_argument("--api", default=API_URL, help="plan: the API (default Azure)")
    parser.add_argument(
        "--whole-day", action="store_true", help="plan: one job for the day, as the app sends"
    )
    parser.add_argument(
        "--reuse", action="store_true", help="plan: every band with all the vans, in order"
    )
    args = parser.parse_args()
    if args.command == "roster":
        day = args.date or tomorrow()
        args.out.write_text(build_roster(day, args.seed), encoding="utf-8")
        print(f"roster: {args.out} for {day}, seed {args.seed}")
        return
    if args.plan and args.crew_only:
        parser.error("--plan needs the pickups: drop --crew-only")
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
