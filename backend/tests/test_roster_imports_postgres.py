"""POST /roster-imports (#229) against Postgres with the migrations.

They insert auth.users rows, so they run only on a throwaway database (CI's
PostGIS service), never against a Supabase host. Through the HTTP API with
tokens signed by a test key, so the role check and RLS are what the app
really does.

The module fixture makes only the two users (dispatcher D, driver A), which
no test changes. Each test's crew carry staff numbers starting T<run>, and
its keys start test-<run>; the `cleanup` fixture deletes them after every
test, so no test sees another's rows. Report times are in 2031, far from
any other test's.
"""

import asyncio
import os
from urllib.parse import urlsplit
from uuid import uuid4

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.config import settings
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

KEY = SigningKey("roster-key")
RUN = uuid4().hex[:6]
STAFF = f"T{RUN}"
HEADER = "staff_no,name,crew_role,pickup_lat,pickup_lon,report_time,request_type"
KILIMANI = "-1.2893,36.7869"
WESTLANDS = "-1.2675,36.8120"
NAKURU = "-0.3031,36.0800"  # about 150 km from the nearest zone


def db(query):
    async def run():
        conn = await asyncpg.connect(DATABASE_URL, statement_cache_size=0)
        try:
            return await query(conn)
        finally:
            await conn.close()

    return asyncio.run(run())


def row(staff: str, name: str, where: str, report: str, request_type: str = "") -> str:
    return f"{STAFF}{staff},{name},cabin_crew,{where},{report},{request_type}"


def roster(*rows: str) -> bytes:
    return "\n".join([HEADER, *rows]).encode()


@pytest.fixture(scope="module")
def users():
    found = {"D": uuid4(), "A": uuid4()}

    async def seed(conn):
        async with conn.transaction():
            for name, uid in found.items():
                await conn.execute("insert into auth.users (id) values ($1)", uid)
                await conn.execute(
                    "insert into public.profiles (id, role, full_name) values ($1, $2, $3)",
                    uid,
                    "dispatcher" if name == "D" else "driver",
                    f"test-{RUN} {name}",
                )

    db(seed)
    yield found

    async def clean(conn):
        async with conn.transaction():
            ids = list(found.values())
            await conn.execute("delete from public.profiles where id = any($1)", ids)
            await conn.execute("delete from auth.users where id = any($1)", ids)

    db(clean)


@pytest.fixture(autouse=True)
def cleanup():
    """Every crew member, pickup and import a test made, deleted after it."""
    yield

    async def clean(conn):
        async with conn.transaction():
            await conn.execute(
                "delete from public.roster_imports where idempotency_key like $1", f"test-{RUN}%"
            )
            await conn.execute(
                "delete from public.pickup_requests p using public.crew_members c "
                "where c.id = p.crew_member_id and c.staff_no like $1",
                f"{STAFF}%",
            )
            await conn.execute(
                "delete from public.crew_members where staff_no like $1", f"{STAFF}%"
            )

    db(clean)


@pytest.fixture
def client(monkeypatch, users):
    monkeypatch.setattr(settings, "database_url", DATABASE_URL)
    monkeypatch.setattr(settings, "travel_model", "haversine")
    monkeypatch.setattr(settings, "solver_pool_size", 1)
    monkeypatch.setattr(app.state, "jwt_keys", FakeJwks(KEY).source(), raising=False)
    monkeypatch.setattr(app.state, "jwt_issuer", ISSUER, raising=False)
    with TestClient(app, headers=bearer(KEY.token(users["D"]))) as client:
        yield client


def upload(client, content: bytes, key: str | None = "first", dry_run: bool = False, **headers):
    if key is not None:
        headers["Idempotency-Key"] = f"test-{RUN}-{key}"
    return client.post(
        "/roster-imports" + ("?dry_run=true" if dry_run else ""),
        files={"file": ("roster.csv", content, "text/csv")},
        headers=headers,
    )


def stored_pickups() -> list[tuple]:
    """(staff_no, name, lat, lon, report_time, request_type, status) of this
    run's pickups."""

    async def read(conn):
        return [
            tuple(r)
            for r in await conn.fetch(
                """
                select c.staff_no, c.name,
                    round(
                        extensions.st_y(p.pickup_location::extensions.geometry)::numeric, 4
                    )::float,
                    round(
                        extensions.st_x(p.pickup_location::extensions.geometry)::numeric, 4
                    )::float,
                    p.report_time, p.request_type, p.status
                from public.pickup_requests p
                join public.crew_members c on c.id = p.crew_member_id
                where c.staff_no like $1
                order by c.staff_no, p.report_time
                """,
                f"{STAFF}%",
            )
        ]

    return db(read)


def crew() -> dict[str, tuple]:
    """staff_no -> (name, role, home lat, home lon) for this run's crew."""

    async def read(conn):
        return {
            r["staff_no"]: (r["name"], r["role"], r["lat"], r["lon"])
            for r in await conn.fetch(
                """
                select staff_no, name, role,
                    round(extensions.st_y(home_location::extensions.geometry)::numeric, 4)::float
                        as lat,
                    round(extensions.st_x(home_location::extensions.geometry)::numeric, 4)::float
                        as lon
                from public.crew_members where staff_no like $1
                """,
                f"{STAFF}%",
            )
        }

    return db(read)


def job_count() -> int:
    return db(lambda conn: conn.fetchval("select count(*) from public.optimization_jobs"))


def test_a_valid_roster_creates_the_crew_and_one_pending_pickup_per_row(client):
    jobs = job_count()
    content = roster(
        row("1", "Amina Hassan", KILIMANI, "2031-05-01T05:30:00+03:00"),
        row("1", "Amina Hassan", WESTLANDS, "2031-05-02T05:30:00+03:00", "standby"),
        row("2", "Brian Mwangi", WESTLANDS, "2031-05-01T06:00:00+03:00", "rostered"),
    )

    response = upload(client, content)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "dry_run": False,
        "rows": 3,
        "crew_created": 2,
        "crew_updated": 0,
        "pickups_created": 3,
        "rows_rejected": 0,
        "rejected": [],
    }
    pickups = stored_pickups()
    assert [(p[0], p[2], p[3], p[5], p[6]) for p in pickups] == [
        (f"{STAFF}1", -1.2893, 36.7869, "rostered", "pending"),
        (f"{STAFF}1", -1.2675, 36.812, "standby", "pending"),
        (f"{STAFF}2", -1.2675, 36.812, "rostered", "pending"),
    ]
    assert pickups[0][4].isoformat() == "2031-05-01T02:30:00+00:00"
    # A new crew member's home is their first pickup point in the file.
    assert crew()[f"{STAFF}1"] == ("Amina Hassan", "cabin_crew", -1.2893, 36.7869)
    assert job_count() == jobs, "an import never starts a re-plan"


def test_every_kind_of_bad_row_is_rejected_and_the_rest_import(client):
    # Known crew member 1, with a pickup on 1 May already.
    first = upload(client, roster(row("1", "Amina", KILIMANI, "2031-05-01T05:30:00+03:00")))
    assert first.status_code == 200, first.text

    content = roster(
        row("1", "Amina Hassan", KILIMANI, "2031-05-03T05:30:00+03:00"),  # 2: fine, renames
        row("2", "Brian", KILIMANI, "not a time"),  # 3: unreadable
        row("3", "Chao", NAKURU, "2031-05-01T05:30:00+03:00"),  # 4: outside the zones
        row("4", "Dana", KILIMANI, "2020-01-01T05:30:00+03:00"),  # 5: past
        row("1", "Amina Hassan", KILIMANI, "2031-05-03T02:30:00Z"),  # 6: same as line 2
        row("1", "Amina Hassan", WESTLANDS, "2031-05-01T05:30:00+03:00"),  # 7: already stored
        row("5", "Esther", WESTLANDS, "2031-05-01T07:00:00+03:00"),  # 8: fine, new
    )

    response = upload(client, content, key="second")

    assert response.status_code == 200, response.text
    body = response.json()
    assert [(r["line"], r["staff_no"], r["reason"]) for r in body["rejected"]] == [
        (3, f"{STAFF}2", "invalid_row"),
        (4, f"{STAFF}3", "outside_pickup_zones"),
        (5, f"{STAFF}4", "report_time_past"),
        (6, f"{STAFF}1", "duplicate_pickup"),
        (7, f"{STAFF}1", "duplicate_pickup"),
    ]
    assert body["rejected"][0]["detail"] == "report_time: not an ISO 8601 date and time"
    assert body["rejected"][4]["detail"] == (
        "this crew member already has a pickup at this report time"
    )
    assert {k: body[k] for k in ["rows", "crew_created", "crew_updated", "pickups_created"]} == {
        "rows": 7,
        "crew_created": 1,
        "crew_updated": 1,
        "pickups_created": 2,
    }
    assert body["rows_rejected"] == 5
    known = crew()
    assert set(known) == {f"{STAFF}1", f"{STAFF}5"}
    # Renamed from the new roster; home stays where it was first recorded.
    assert known[f"{STAFF}1"] == ("Amina Hassan", "cabin_crew", -1.2893, 36.7869)
    assert len(stored_pickups()) == 3


def test_a_dry_run_reports_the_same_result_and_writes_nothing(client):
    content = roster(
        row("1", "Amina", KILIMANI, "2031-05-01T05:30:00+03:00"),
        row("2", "Chao", NAKURU, "2031-05-01T05:30:00+03:00"),
    )

    dry = upload(client, content, key=None, dry_run=True)

    assert dry.status_code == 200, dry.text
    assert dry.json()["dry_run"] is True
    assert crew() == {}
    assert stored_pickups() == []
    stored = db(
        lambda conn: conn.fetchval(
            "select count(*) from public.roster_imports where idempotency_key like $1",
            f"test-{RUN}%",
        )
    )
    assert stored == 0

    real = upload(client, content)

    assert real.status_code == 200, real.text
    assert real.json() == dry.json() | {"dry_run": False}
    assert len(stored_pickups()) == 1


def test_a_retry_with_the_same_key_imports_nothing_and_gets_the_first_result(client):
    content = roster(row("1", "Amina", KILIMANI, "2031-05-01T05:30:00+03:00"))

    first = upload(client, content)
    retry = upload(client, content)

    assert first.status_code == retry.status_code == 200, retry.text
    assert retry.json() == first.json()
    assert retry.json()["pickups_created"] == 1
    assert len(stored_pickups()) == 1


def test_the_same_key_with_a_different_file_is_refused(client):
    assert upload(client, roster(row("1", "A", KILIMANI, "2031-05-01T05:30:00+03:00"))).is_success

    other = upload(client, roster(row("2", "B", KILIMANI, "2031-05-01T05:30:00+03:00")))

    assert other.status_code == 422
    assert other.json()["code"] == "idempotency_key_reused"
    assert set(crew()) == {f"{STAFF}1"}


def test_a_real_import_needs_an_idempotency_key(client):
    response = upload(
        client, roster(row("1", "A", KILIMANI, "2031-05-01T05:30:00+03:00")), key=None
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_failed"
    assert crew() == {}


def test_a_file_missing_a_column_imports_nothing(client):
    content = b"staff_no,name,pickup_lat,pickup_lon,report_time\n" + (
        f"{STAFF}1,A,{KILIMANI},2031-05-01T05:30:00+03:00".encode()
    )

    response = upload(client, content)

    assert response.status_code == 422
    assert response.json() == {
        "code": "validation_failed",
        "detail": "missing columns: crew_role",
    }
    assert crew() == {}


def test_a_driver_may_not_import(client, users):
    content = roster(row("1", "A", KILIMANI, "2031-05-01T05:30:00+03:00"))

    response = upload(client, content, **bearer(KEY.token(users["A"])))

    assert response.status_code == 403
    assert crew() == {}
