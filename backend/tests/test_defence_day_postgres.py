"""The defence day (scripts/make_defence_day.py, #252) against Postgres with
the migrations: seed writes the day, seeding twice gives the same rows, the
bands get their own vans, and reset leaves every table as it was, the named
crew's records included.

They insert auth.users rows for the 20 drivers and the 8 named crew, so they
run only on a throwaway database: when DATABASE_URL is set in the
environment (CI's PostGIS service), never against a Supabase host.
"""

import asyncio
import importlib.util
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import asyncpg
import pytest

DATABASE_URL = os.environ.get("DATABASE_URL")
pytestmark = [
    pytest.mark.skipif(not DATABASE_URL, reason="needs DATABASE_URL in the environment"),
    pytest.mark.skipif(
        bool(DATABASE_URL) and "supabase" in (urlsplit(DATABASE_URL).hostname or ""),
        reason="inserts auth.users rows: never against Supabase",
    ),
]

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "make_defence_day", ROOT / "scripts" / "make_defence_day.py"
)
defence = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(defence)
accounts = defence.accounts

RUN = uuid4().hex[:8]
DAY = date(2030, 3, 15)
HOME = "SRID=4326;POINT(36.812 -1.2675)"
TABLES = [
    "auth.users",
    "public.profiles",
    "public.crew_members",
    "public.vehicles",
    "public.pickup_requests",
    "public.optimization_jobs",
    "public.routes",
    "public.route_nodes",
    "public.crew_messages",
]


def db(query):
    async def run():
        conn = await asyncpg.connect(DATABASE_URL, statement_cache_size=0)
        try:
            return await query(conn)
        finally:
            await conn.close()

    return asyncio.run(run())


async def snapshot(conn) -> dict[str, list[str]]:
    return {
        t: [
            r[0]
            for r in await conn.fetch(
                f"select (to_jsonb(t) - 'created_at')::text from {t} t order by 1"
            )
        ]
        for t in TABLES
    }


@pytest.fixture
def world():
    """The accounts seed_test_accounts.py makes, and a bystander: a crew
    member with no account and a pickup on the day."""
    users = {
        **{email: (uuid4(), "driver") for _, email, _ in accounts.DEFENCE_VANS},
        **{c.email: (uuid4(), "crew") for c in accounts.NAMED_CREW},
    }
    named = {c.staff_no: c for c in accounts.NAMED_CREW}
    state = {}

    async def setup(conn):
        async with conn.transaction():
            for email, (uid, role) in users.items():
                await conn.execute("insert into auth.users (id, email) values ($1, $2)", uid, email)
                await conn.execute(
                    "insert into public.profiles (id, role, full_name) values ($1, $2, $3)",
                    uid,
                    role,
                    f"test-{RUN} {email}",
                )
            for staff_no, c in named.items():
                await conn.execute(
                    "insert into public.crew_members (profile_id, staff_no, name, role, "
                    "home_location) values ($1, $2, $3, $4, $5)",
                    users[c.email][0],
                    staff_no,
                    c.name,
                    c.role,
                    HOME,
                )
            state["crew"] = await conn.fetchval(
                "insert into public.crew_members (name, role, home_location) "
                "values ($1, 'cabin_crew', $2) returning id",
                f"test-{RUN} bystander",
                HOME,
            )
            state["pickup"] = await conn.fetchval(
                "insert into public.pickup_requests (crew_member_id, pickup_location, "
                "report_time, request_type) values ($1, $2, $3, 'rostered') returning id",
                state["crew"],
                HOME,
                datetime.combine(DAY, datetime.min.time(), defence.EAT) + timedelta(hours=5),
            )

    async def teardown(conn):
        await defence.reset(conn)
        ids = [uid for uid, _ in users.values()]
        async with conn.transaction():
            await conn.execute("delete from public.pickup_requests where id = $1", state["pickup"])
            await conn.execute(
                "delete from public.crew_members where id = $1 or profile_id = any($2)",
                state["crew"],
                ids,
            )
            await conn.execute("delete from public.profiles where id = any($1)", ids)
            await conn.execute("delete from auth.users where id = any($1)", ids)

    try:
        db(setup)
        yield state
    finally:
        db(teardown)


def test_seed_writes_the_day_and_reset_puts_everything_back(world):
    before = db(snapshot)
    summary = db(lambda conn: defence.seed_day(conn, DAY, defence.DEFAULT_SEED, crew_only=False))
    assert summary["crew"] == 120 and summary["pickups"] == 120

    async def counts(conn):
        return (
            await conn.fetchval(
                "select count(*) from public.vehicles v join public.profiles p "
                "on p.id = v.assigned_driver_id where v.plate_number like 'defence-%'"
            ),
            await conn.fetchval(
                "select count(*) from public.crew_members where name like 'defence-%'"
            ),
            await conn.fetchval(
                "select count(*) from public.pickup_requests p join public.crew_members c "
                "on c.id = p.crew_member_id where c.name like 'defence-%' or c.staff_no = any($1)",
                [c.staff_no for c in accounts.NAMED_CREW],
            ),
        )

    assert db(counts) == (20, 112, 120)
    # Seeding again gives the same rows.
    seeded = db(snapshot)
    db(lambda conn: defence.seed_day(conn, DAY, defence.DEFAULT_SEED, crew_only=False))
    assert db(snapshot) == seeded

    db(defence.reset)
    after = db(snapshot)
    assert after == before  # the named crew and the bystander as they were


def test_crew_only_writes_no_pickups(world):
    summary = db(lambda conn: defence.seed_day(conn, DAY, defence.DEFAULT_SEED, crew_only=True))
    assert summary["pickups"] == 0
    assert (
        db(
            lambda conn: conn.fetchval(
                "select count(*) from public.pickup_requests p join public.crew_members c "
                "on c.id = p.crew_member_id where c.name like 'defence-%'"
            )
        )
        == 0
    )


def test_each_band_is_planned_with_its_own_vans(world):
    db(lambda conn: defence.seed_day(conn, DAY, defence.DEFAULT_SEED, crew_only=False))
    jobs = db(lambda conn: defence.band_jobs(conn, DAY, defence.DEFAULT_SEED))
    assert [(band, len(p), len(v)) for band, p, v in jobs] == [
        ("early", 42, 7),
        ("mid", 24, 4),
        ("noon", 18, 3),
        ("afternoon", 18, 3),
        ("night", 18, 3),
    ]
    # The bystander's pickup on the same day is in no band.
    assert all(world["pickup"] not in p for _, p, _ in jobs)
    assert len({v for _, _, vans in jobs for v in vans}) == 20
    # --whole-day: the one job the app's Plan tab would send.
    [(name, pickups, vans)] = defence.whole_day(jobs)
    assert (name, len(set(pickups)), len(set(vans))) == ("whole-day", 120, 20)
    # --reuse: each band in order, with all 20 vans.
    reused = defence.reuse_fleet(jobs)
    assert [(band, p) for band, p, _ in reused] == [(band, p) for band, p, _ in jobs]
    assert all(len(set(vans)) == 20 for _, _, vans in reused)


def test_seed_stops_without_the_accounts():
    with pytest.raises(SystemExit, match="seed_test_accounts.py"):
        db(lambda conn: defence.seed_day(conn, DAY, defence.DEFAULT_SEED, crew_only=False))
