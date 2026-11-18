"""Add pickup, Set home, crew search and a pin's nearest zone (#253) against
Postgres with the migrations, through the HTTP API with tokens signed by a
test key, so the role check and RLS are what the app really does.

They insert auth.users rows, so they run only on a throwaway database (CI's
PostGIS service), never against a Supabase host. Each test's crew carry
staff numbers starting M<run> and names starting test-<run>; `cleanup`
deletes them, and their pickups, after every test. Report times are in 2031.
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

KEY = SigningKey("manual-key")
RUN = uuid4().hex[:6]
STAFF = f"M{RUN}"
NAME = f"test-{RUN}"
# Zone points (0 km from their zone), and one about 130 km out.
KILIMANI = {"lat": -1.2893, "lon": 36.7869}
WESTLANDS = {"lat": -1.2675, "lon": 36.812}
NAKURU = {"lat": -0.3031, "lon": 36.08}
REPORT = "2031-05-01T05:30:00+03:00"
ROSTER_HEADER = "staff_no,name,crew_role,pickup_location,report_time"


def db(query):
    async def run():
        conn = await asyncpg.connect(DATABASE_URL, statement_cache_size=0)
        try:
            return await query(conn)
        finally:
            await conn.close()

    return asyncio.run(run())


@pytest.fixture(scope="module")
def users():
    found = {"dispatcher": uuid4(), "driver": uuid4(), "crew": uuid4()}

    async def seed(conn):
        async with conn.transaction():
            for role, uid in found.items():
                await conn.execute("insert into auth.users (id) values ($1)", uid)
                await conn.execute(
                    "insert into public.profiles (id, role, full_name) values ($1, $2, $3)",
                    uid,
                    role,
                    f"{NAME} {role}",
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
    yield

    async def clean(conn):
        async with conn.transaction():
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
    with TestClient(app, headers=bearer(KEY.token(users["dispatcher"]))) as client:
        yield client


def add_crew(n: str, name: str, home: dict = KILIMANI) -> str:
    return str(
        db(
            lambda conn: conn.fetchval(
                "insert into public.crew_members (staff_no, name, role, home_location) "
                "values ($1, $2, 'cabin_crew', "
                "extensions.st_setsrid(extensions.st_makepoint($4, $3), 4326)) returning id",
                f"{STAFF}{n}",
                f"{NAME} {name}",
                home["lat"],
                home["lon"],
            )
        )
    )


def post(client, body: dict, key: str = "one"):
    return client.post(
        "/pickup-requests", json=body, headers={"Idempotency-Key": f"test-{RUN}-{key}"}
    )


def pickups() -> list[tuple]:
    """(staff_no, lat, lon, report_time, request_type, status) of this run's."""

    async def read(conn):
        return [
            tuple(r)
            for r in await conn.fetch(
                """
                select c.staff_no,
                    round(extensions.st_y(p.pickup_location::extensions.geometry)::numeric, 4)
                        ::float,
                    round(extensions.st_x(p.pickup_location::extensions.geometry)::numeric, 4)
                        ::float,
                    p.report_time, p.request_type, p.status
                from public.pickup_requests p
                join public.crew_members c on c.id = p.crew_member_id
                where c.staff_no like $1 order by c.staff_no, p.report_time
                """,
                f"{STAFF}%",
            )
        ]

    return db(read)


def home_of(crew_id: str) -> tuple[float, float]:
    async def read(conn):
        r = await conn.fetchrow(
            "select round(extensions.st_y(home_location::extensions.geometry)::numeric, 4)"
            "::float as lat, round(extensions.st_x(home_location::extensions.geometry)"
            "::numeric, 4)::float as lon from public.crew_members where id = $1",
            crew_id,
        )
        return (r["lat"], r["lon"])

    return db(read)


def jobs() -> int:
    return db(lambda conn: conn.fetchval("select count(*) from public.optimization_jobs"))


def test_a_pickup_at_home_and_one_elsewhere(client):
    amina = add_crew("1", "Amina")
    before = jobs()

    at_home = post(client, {"crew_member_id": amina, "report_time": REPORT}, key="home")
    elsewhere = post(
        client,
        {
            "crew_member_id": amina,
            "report_time": "2031-05-02T05:30:00+03:00",
            "request_type": "standby",
            "pickup_location": WESTLANDS,
        },
        key="elsewhere",
    )

    assert (at_home.status_code, elsewhere.status_code) == (201, 201), elsewhere.text
    body = at_home.json()
    assert body["crew_name"] == f"{NAME} Amina" and body["status"] == "pending"
    assert (body["lat"], body["lon"]) == (KILIMANI["lat"], KILIMANI["lon"])
    assert elsewhere.json()["zone_label"].startswith("Westlands")
    assert [(lat, lon, t) for _, lat, lon, _, t, _ in pickups()] == [
        (-1.2893, 36.7869, "rostered"),
        (-1.2675, 36.812, "standby"),
    ]
    assert jobs() == before  # no re-plan


def import_reason(client, staff_no: str, where: str, report: str) -> str:
    """The roster import's reject reason for the same pickup, in a dry run."""
    content = f'{ROSTER_HEADER}\n{staff_no},x,cabin_crew,"{where}",{report}'.encode()
    response = client.post(
        "/roster-imports?dry_run=true", files={"file": ("r.csv", content, "text/csv")}
    )
    assert response.status_code == 200, response.text
    [rejected] = response.json()["rejected"]
    return rejected["reason"]


def test_rejected_for_the_same_reasons_as_the_import(client):
    brian = add_crew("2", "Brian")
    assert (
        post(client, {"crew_member_id": brian, "report_time": REPORT}, key="first").status_code
        == 201
    )

    past, later = "2020-01-01T05:30:00+03:00", "2031-05-03T05:30:00+03:00"
    nakuru = f"{NAKURU['lat']}, {NAKURU['lon']}"
    cases = [
        ("report_time_past", {"report_time": past}, "", past),
        ("outside_pickup_zones", {"report_time": later, "pickup_location": NAKURU}, nakuru, later),
        ("duplicate_pickup", {"report_time": REPORT}, "", REPORT),
    ]
    for reason, changes, where, report in cases:
        response = post(client, {"crew_member_id": brian} | changes, key=reason)
        assert response.status_code == 422, response.text
        assert response.json()["code"] == reason
        assert import_reason(client, f"{STAFF}2", where, report) == reason
    assert len(pickups()) == 1


def test_a_retry_returns_the_same_pickup_and_a_reused_key_is_refused(client):
    chao = add_crew("3", "Chao")
    body = {"crew_member_id": chao, "report_time": REPORT}

    first, again = post(client, body), post(client, body)
    other = post(client, body | {"report_time": "2031-05-04T05:30:00+03:00"})

    assert (first.status_code, again.status_code) == (201, 201)
    assert again.json() == first.json()
    assert (other.status_code, other.json()["code"]) == (422, "idempotency_key_reused")
    assert len(pickups()) == 1


def test_an_unknown_crew_member_is_404(client):
    response = post(client, {"crew_member_id": str(uuid4()), "report_time": REPORT})
    assert (response.status_code, response.json()["code"]) == (404, "not_found")
    response = client.patch(f"/crew-members/{uuid4()}/home", json=KILIMANI)
    assert (response.status_code, response.json()["code"]) == (404, "not_found")


def test_set_home_moves_it_and_keeps_stored_pickups_where_they_were(client):
    daniel = add_crew("4", "Daniel")
    assert post(client, {"crew_member_id": daniel, "report_time": REPORT}).status_code == 201

    moved = client.patch(f"/crew-members/{daniel}/home", json=WESTLANDS)

    assert moved.status_code == 200, moved.text
    body = moved.json()
    assert body["home"] == WESTLANDS and body["zone_label"].startswith("Westlands")
    assert body["distance_km"] == 0.0
    assert home_of(daniel) == (WESTLANDS["lat"], WESTLANDS["lon"])
    [(_, lat, lon, *_)] = pickups()
    assert (lat, lon) == (KILIMANI["lat"], KILIMANI["lon"])
    # The next pickup at home is collected from the new one.
    later = post(
        client, {"crew_member_id": daniel, "report_time": "2031-05-05T05:30:00+03:00"}, "2"
    )
    assert (later.json()["lat"], later.json()["lon"]) == (WESTLANDS["lat"], WESTLANDS["lon"])


def test_set_home_beyond_10_km_is_refused_and_changes_nothing(client):
    esther = add_crew("5", "Esther")
    response = client.patch(f"/crew-members/{esther}/home", json=NAKURU)
    assert (response.status_code, response.json()["code"]) == (422, "outside_pickup_zones")
    assert home_of(esther) == (KILIMANI["lat"], KILIMANI["lon"])


def test_nearest_zone_is_the_imports_zone_check(client):
    near = client.get("/pickup-zones/nearest", params=KILIMANI).json()
    far = client.get("/pickup-zones/nearest", params=NAKURU).json()
    assert near["zone_label"].startswith("Kilimani")
    assert (near["distance_km"], near["within_pickup_zones"]) == (0.0, True)
    assert far["distance_km"] > 100 and far["within_pickup_zones"] is False


def test_crew_search_by_name_or_staff_number_in_pages(client):
    faith = add_crew("6", "Faith Chebet")
    george = add_crew("7", "George Njuguna", home=WESTLANDS)

    def search(q: str, **params) -> dict:
        response = client.get("/crew-members", params={"q": q} | params)
        assert response.status_code == 200, response.text
        return response.json()

    assert [c["id"] for c in search(f"{NAME} faith")["items"]] == [faith]
    assert [c["id"] for c in search(f"{STAFF}7".lower())["items"]] == [george]
    item = search(f"{STAFF}7")["items"][0]
    assert item == {
        "id": george,
        "staff_no": f"{STAFF}7",
        "name": f"{NAME} George Njuguna",
        "crew_role": "cabin_crew",
        "home": WESTLANDS,
        "home_zone_label": item["home_zone_label"],
    }
    assert item["home_zone_label"].startswith("Westlands")
    first = search(NAME, limit=1)
    assert [c["id"] for c in first["items"]] == [faith] and first["next_cursor"]
    second = search(NAME, limit=1, cursor=first["next_cursor"])
    assert [c["id"] for c in second["items"]] == [george] and second["next_cursor"] is None
    # A % typed in the search box is a plain character, not a LIKE wildcard.
    assert search(f"{NAME}%")["items"] == []


@pytest.mark.parametrize("role", ["crew", "driver"])
def test_crew_and_drivers_get_403_everywhere(client, users, role):
    amina = add_crew("8", "Amina")
    headers = bearer(KEY.token(users[role])) | {"Idempotency-Key": f"test-{RUN}-{role}"}
    responses = [
        client.get("/crew-members", headers=headers),
        client.get("/pickup-zones/nearest", params=KILIMANI, headers=headers),
        client.post(
            "/pickup-requests",
            json={"crew_member_id": amina, "report_time": REPORT},
            headers=headers,
        ),
        client.patch(f"/crew-members/{amina}/home", json=WESTLANDS, headers=headers),
    ]
    assert [(r.status_code, r.json()["code"]) for r in responses] == [(403, "forbidden")] * 4
    assert pickups() == [] and home_of(amina) == (KILIMANI["lat"], KILIMANI["lon"])
