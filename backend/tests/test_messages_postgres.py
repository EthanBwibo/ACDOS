"""Crew-to-dispatcher preset messages (#54) against Postgres with the
migrations.

They insert auth.users rows, so they run only on a throwaway database: when
DATABASE_URL is set in the environment (CI's PostGIS service), never against
a Supabase host. Through the HTTP API with tokens signed by a test key.

Each test seeds its own world (fresh ids, deleted afterwards by id):
dispatcher D, driver A, crew accounts C and E with crew records, and a crew
account N without one.
"""

import asyncio
import os
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app import reads
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

KEY = SigningKey("messages-key")
RUN = uuid4().hex[:8]
PRESETS = ["at_pickup_point", "cannot_find_van", "flight_changed", "please_call_me", "running_late"]


def db(query):
    async def run():
        conn = await asyncpg.connect(DATABASE_URL, statement_cache_size=0)
        try:
            return await query(conn)
        finally:
            await conn.close()

    return asyncio.run(run())


class World:
    def __init__(self) -> None:
        self.users = {name: uuid4() for name in ["D", "A", "C", "E", "N"]}
        self.crew: dict[str, UUID] = {}


async def seed(conn, w: World) -> None:
    roles = {"D": "dispatcher", "A": "driver", "C": "crew", "E": "crew", "N": "crew"}
    async with conn.transaction():
        for name, uid in w.users.items():
            await conn.execute("insert into auth.users (id) values ($1)", uid)
            await conn.execute(
                "insert into public.profiles (id, role, full_name) values ($1, $2, $3)",
                uid,
                roles[name],
                f"test-{RUN} {name}",
            )
        for name in ["C", "E"]:
            w.crew[name] = await conn.fetchval(
                "insert into public.crew_members (profile_id, name, role, home_location) "
                "values ($1, $2, 'cabin_crew', 'SRID=4326;POINT(36.812 -1.2675)') returning id",
                w.users[name],
                f"test-{RUN} crew {name}",
            )


async def clean(conn, w: World) -> None:
    async with conn.transaction():
        crew = list(w.crew.values())
        await conn.execute("delete from public.crew_messages where crew_member_id = any($1)", crew)
        await conn.execute("delete from public.crew_members where id = any($1)", crew)
        users = list(w.users.values())
        await conn.execute("delete from public.profiles where id = any($1)", users)
        await conn.execute("delete from auth.users where id = any($1)", users)


@pytest.fixture
def world():
    w = World()
    try:
        db(lambda conn: seed(conn, w))
        yield w
    finally:
        db(lambda conn: clean(conn, w))


@pytest.fixture
def client(monkeypatch, world):
    monkeypatch.setattr(settings, "database_url", DATABASE_URL)
    monkeypatch.setattr(settings, "travel_model", "haversine")
    monkeypatch.setattr(settings, "solver_pool_size", 1)
    monkeypatch.setattr(app.state, "jwt_keys", FakeJwks(KEY).source(), raising=False)
    monkeypatch.setattr(app.state, "jwt_issuer", ISSUER, raising=False)
    with TestClient(app) as client:
        yield client


def as_user(world: World, name: str) -> dict:
    return bearer(KEY.token(world.users[name]))


def send(client, world, name, code="running_late", key=None):
    headers = as_user(world, name) | {"Idempotency-Key": key or f"test-{RUN}-{uuid4().hex}"}
    return client.post("/messages", json={"preset_code": code}, headers=headers)


def stored(world: World) -> list:
    return db(
        lambda conn: conn.fetch(
            "select * from public.crew_messages where crew_member_id = any($1) "
            "order by sent_at, id",
            list(world.crew.values()),
        )
    )


def job_count() -> int:
    return db(lambda conn: conn.fetchval("select count(*) from public.optimization_jobs"))


@pytest.mark.parametrize("user", ["C", "D"])
def test_crew_and_the_dispatcher_get_the_fixed_presets(client, world, user):
    response = client.get("/preset-messages", headers=as_user(world, user))
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert [i["code"] for i in items] == PRESETS
    assert all(i["label"] for i in items)


def test_crew_send_a_preset_to_the_dispatcher(client, world):
    response = send(client, world, "C", "cannot_find_van")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["crew_member_id"] == str(world.crew["C"])
    assert body["crew_name"] == f"test-{RUN} crew C"
    assert (body["preset_code"], body["label"]) == ("cannot_find_van", "I cannot find the van")
    assert body["read_at"] is None
    [row] = stored(world)
    assert str(row["id"]) == body["id"]


def test_a_retried_send_does_not_duplicate_the_message(client, world):
    key = f"test-{RUN}-retry"
    first = send(client, world, "C", key=key)
    again = send(client, world, "C", key=key)
    assert again.status_code == 200
    assert again.json() == first.json()
    assert len(stored(world)) == 1


@pytest.mark.parametrize(
    ("sender", "code"),
    [("C", "please_call_me"), ("E", "running_late")],
    ids=["same-crew-other-preset", "other-crew-same-preset"],
)
def test_a_key_already_used_for_another_message_is_refused(client, world, sender, code):
    key = f"test-{RUN}-used"
    send(client, world, "C", "running_late", key=key)
    response = send(client, world, sender, code, key=key)
    assert (response.status_code, response.json()["code"]) == (422, "idempotency_key_reused")
    assert len(stored(world)) == 1


def test_an_unknown_preset_is_refused(client, world):
    response = send(client, world, "C", "free text is not a preset")
    assert (response.status_code, response.json()["code"]) == (422, "validation_failed")
    assert stored(world) == []


@pytest.mark.parametrize("sender", ["A", "D", "N"], ids=["driver", "dispatcher", "no-crew-record"])
def test_only_crew_with_a_record_may_send(client, world, sender):
    response = send(client, world, sender)
    assert (response.status_code, response.json()["code"]) == (403, "forbidden")
    assert stored(world) == []


def test_sending_any_preset_creates_no_optimisation_job(client, world):
    jobs = job_count()
    for code in PRESETS:
        assert send(client, world, "C", code).status_code == 200
    assert job_count() == jobs
    assert len(stored(world)) == len(PRESETS)


def ids_of(items, world) -> list[str]:
    ours = {str(r["id"]) for r in stored(world)}
    return [i["id"] for i in items if i["id"] in ours]


def walk(client, world, user, query="") -> list[dict]:
    items, cursor = [], None
    while True:
        path = f"/messages?limit=2{query}" + (f"&cursor={cursor}" if cursor else "")
        body = client.get(path, headers=as_user(world, user)).json()
        items += body["items"]
        cursor = body["next_cursor"]
        if cursor is None:
            return items


def test_crew_list_their_own_messages_and_the_dispatcher_every_ones(client, world):
    sent = [send(client, world, name).json()["id"] for name in ["C", "E", "C"]]
    newest_first = list(reversed(sent))

    assert ids_of(walk(client, world, "C"), world) == [sent[2], sent[0]]
    assert ids_of(walk(client, world, "E"), world) == [sent[1]]
    assert ids_of(walk(client, world, "D"), world) == newest_first
    response = client.get("/messages", headers=as_user(world, "A"))
    assert response.status_code == 403


def test_the_dispatcher_marks_a_message_read_once(client, world):
    first, second = (send(client, world, "C").json()["id"] for _ in range(2))
    path = f"/messages/{first}/ack"

    read = client.post(path, headers=as_user(world, "D"))
    assert read.status_code == 200, read.text
    assert read.json()["id"] == first
    # Acknowledging twice leaves the first time unchanged.
    assert client.post(path, headers=as_user(world, "D")).json() == read.json()
    rows = {str(r["id"]): r["read_at"] for r in stored(world)}
    assert rows[second] is None and rows[first] is not None

    assert ids_of(walk(client, world, "D", "&unread=true"), world) == [second]
    mine = {i["id"]: i["read_at"] for i in walk(client, world, "C")}
    assert mine[first] == read.json()["read_at"]


@pytest.mark.parametrize("user", ["C", "A"])
def test_only_the_dispatcher_may_mark_a_message_read(client, world, user):
    message = send(client, world, "C").json()["id"]
    response = client.post(f"/messages/{message}/ack", headers=as_user(world, user))
    assert response.status_code == 403
    assert stored(world)[0]["read_at"] is None


def test_an_unknown_message_is_404(client, world):
    response = client.post(f"/messages/{uuid4()}/ack", headers=as_user(world, "D"))
    assert (response.status_code, response.json()["code"]) == (404, "not_found")


# RLS (028), as each role, in a transaction rolled back at the end.


def as_role(world: World, name: str, steps):
    async def run(conn):
        tx = conn.transaction()
        await tx.start()
        try:
            await reads.become(conn, world.users[name])
            return await steps(conn)
        finally:
            await tx.rollback()

    return db(run)


def insert_as(world: World, name: str, crew: str, read: bool = False):
    async def steps(conn):
        await conn.execute(
            "insert into public.crew_messages "
            "(crew_member_id, preset_message_id, idempotency_key, read_at) "
            "select $1, id, $2, case when $3 then now() end from public.preset_messages "
            "where code = 'running_late'",
            world.crew[crew],
            f"test-{RUN}-{uuid4().hex}",
            read,
        )

    return as_role(world, name, steps)


def test_crew_cannot_send_as_someone_else_or_already_read(world):
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        insert_as(world, "C", "E")
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        insert_as(world, "C", "C", read=True)
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        insert_as(world, "A", "C")
    insert_as(world, "C", "C")  # their own, unread: allowed


def test_drivers_see_nothing_and_crew_only_their_own(client, world):
    send(client, world, "C")
    send(client, world, "E")

    def seen(name):
        async def steps(conn):
            return (
                await conn.fetchval(
                    "select count(*) from public.crew_messages where crew_member_id = any($1)",
                    list(world.crew.values()),
                ),
                await conn.fetchval("select count(*) from public.preset_messages"),
                await conn.fetchval(
                    "select count(*) from public.crew_members where id = any($1)",
                    list(world.crew.values()),
                ),
            )

        return as_role(world, name, steps)

    assert seen("A") == (0, 0, 0)
    assert seen("C") == (1, len(PRESETS), 1)
    assert seen("D") == (2, len(PRESETS), 2)


def test_crew_cannot_mark_read_edit_or_delete_and_nobody_edits_presets(client, world):
    message = UUID(send(client, world, "C").json()["id"])

    async def crew_marks_read(conn):
        return await conn.execute(
            "update public.crew_messages set read_at = now() where id = $1", message
        )

    # No crew update policy: the row is not theirs to update.
    assert as_role(world, "C", crew_marks_read) == "UPDATE 0"

    refused = [
        ("C", "update public.crew_messages set preset_message_id = preset_message_id "
              "where id = $1"),
        ("D", "update public.crew_messages set crew_member_id = crew_member_id where id = $1"),
        ("C", "delete from public.crew_messages where id = $1"),
        ("D", "delete from public.crew_messages where id = $1"),
        ("D", "update public.preset_messages set label = 'x' where $1::uuid is not null"),
        ("D", "insert into public.preset_messages (code, label) "
              "select 'free_text', 'x' where $1::uuid is not null"),
    ]  # fmt: skip
    for name, query in refused:

        async def attempt(conn, query=query):
            await conn.execute(query, message)

        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            as_role(world, name, attempt)
    assert stored(world)[0]["read_at"] is None
