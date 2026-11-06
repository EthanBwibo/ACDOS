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
REPLIES = ["call_dispatcher", "noted", "van_rerouted"]


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


@pytest.mark.parametrize("user, presets", [("C", PRESETS), ("D", REPLIES)])
def test_crew_and_the_dispatcher_get_the_presets_they_may_send(client, world, user, presets):
    response = client.get("/preset-messages", headers=as_user(world, user))
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert [i["code"] for i in items] == presets
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


@pytest.mark.parametrize("code", ["free text is not a preset", "noted"])
def test_an_unknown_preset_or_a_reply_preset_is_refused(client, world, code):
    response = send(client, world, "C", code)
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


def reply(client, world, message, code="noted", user="D", key=None):
    headers = as_user(world, user) | {"Idempotency-Key": key or f"test-{RUN}-{uuid4().hex}"}
    return client.post(f"/messages/{message}/replies", json={"preset_code": code}, headers=headers)


def own_messages(client, world, user):
    return client.get("/messages", headers=as_user(world, user)).json()["items"]


def test_a_reply_reaches_only_the_crew_member_who_sent_the_message(client, world):
    theirs = send(client, world, "C").json()["id"]
    send(client, world, "E")

    response = reply(client, world, theirs, "van_rerouted")

    assert response.status_code == 200, response.text
    assert response.json()["label"] == "Van rerouted"
    mine = own_messages(client, world, "C")
    assert [r["preset_code"] for r in mine[0]["replies"]] == ["van_rerouted"]
    assert own_messages(client, world, "E")[0]["replies"] == []


def test_replying_marks_the_message_read(client, world):
    message = send(client, world, "C").json()["id"]
    reply(client, world, message)
    assert stored(world)[0]["read_at"] is not None


def test_replies_come_oldest_first(client, world):
    message = send(client, world, "C").json()["id"]
    reply(client, world, message, "noted")
    reply(client, world, message, "call_dispatcher")

    replies = own_messages(client, world, "D")[0]["replies"]

    assert [r["preset_code"] for r in replies] == ["noted", "call_dispatcher"]


def test_a_retried_reply_is_sent_once(client, world):
    message = send(client, world, "C").json()["id"]
    key = f"test-{RUN}-reply"

    first = reply(client, world, message, key=key)
    second = reply(client, world, message, key=key)

    assert first.status_code == 200, first.text
    assert second.json() == first.json()
    assert len(own_messages(client, world, "C")[0]["replies"]) == 1


def test_a_key_used_for_another_reply_is_refused(client, world):
    first, other = (send(client, world, "C").json()["id"] for _ in range(2))
    key = f"test-{RUN}-reply-used"
    reply(client, world, first, key=key)

    for message, code in [(other, "noted"), (first, "van_rerouted")]:
        response = reply(client, world, message, code, key=key)
        assert (response.status_code, response.json()["code"]) == (422, "idempotency_key_reused")


@pytest.mark.parametrize("code", ["free text is not a preset", "running_late"])
def test_a_reply_must_be_a_reply_preset(client, world, code):
    message = send(client, world, "C").json()["id"]
    response = reply(client, world, message, code)
    assert (response.status_code, response.json()["code"]) == (422, "validation_failed")
    assert stored(world)[0]["read_at"] is None


@pytest.mark.parametrize("user", ["C", "A"])
def test_only_the_dispatcher_may_reply(client, world, user):
    message = send(client, world, "C").json()["id"]
    assert reply(client, world, message, user=user).status_code == 403


def test_a_reply_to_an_unknown_message_is_404(client, world):
    response = reply(client, world, uuid4())
    assert (response.status_code, response.json()["code"]) == (404, "not_found")


def test_a_reply_never_starts_a_job(client, world):
    message = send(client, world, "C").json()["id"]
    before = job_count()
    reply(client, world, message)
    assert job_count() == before


# RLS (028, 029), as each role, in a transaction rolled back at the end.


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
    """Insert a message as name for crew's crew member. The preset id is read
    as postgres and given as a value, so the insert policy itself decides
    (a select under RLS could just match no presets and insert nothing)."""
    preset = db(
        lambda conn: conn.fetchval(
            "select id from public.preset_messages where code = 'running_late'"
        )
    )

    async def steps(conn):
        return await conn.execute(
            "insert into public.crew_messages "
            "(crew_member_id, preset_message_id, idempotency_key, read_at) "
            "values ($1, $2, $3, case when $4 then now() end)",
            world.crew[crew],
            preset,
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
    assert insert_as(world, "C", "C") == "INSERT 0 1"  # their own, unread: allowed


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


def preset_id(code: str) -> UUID:
    return db(
        lambda conn: conn.fetchval("select id from public.preset_messages where code = $1", code)
    )


def insert_reply(world: World, user: str, message: str, code: str = "noted", sender: str = "D"):
    preset = preset_id(code)  # read first: as_role is already inside a loop

    async def attempt(conn):
        await conn.execute(
            "insert into public.message_replies "
            "(crew_message_id, preset_message_id, dispatcher_id, idempotency_key) "
            "values ($1, $2, $3, $4)",
            UUID(message),
            preset,
            world.users[sender],
            f"test-{RUN}-{uuid4().hex}",
        )

    as_role(world, user, attempt)


@pytest.mark.parametrize(
    "user, code, sender",
    [
        ("C", "noted", "C"),  # crew can't reply
        ("A", "noted", "A"),  # nor can drivers
        ("D", "running_late", "D"),  # a dispatcher can't send a crew preset
        ("D", "noted", "C"),  # or reply as someone else
    ],
)
def test_rls_keeps_replies_to_dispatchers_and_their_presets(client, world, user, code, sender):
    message = send(client, world, "C").json()["id"]
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        insert_reply(world, user, message, code, sender)


def test_rls_keeps_crew_to_crew_presets(client, world):
    preset = preset_id("noted")

    async def attempt(conn):
        await conn.execute(
            "insert into public.crew_messages "
            "(crew_member_id, preset_message_id, idempotency_key) values ($1, $2, $3)",
            world.crew["C"],
            preset,
            f"test-{RUN}-{uuid4().hex}",
        )

    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        as_role(world, "C", attempt)


@pytest.mark.parametrize("user, seen", [("C", 1), ("D", 1), ("E", 0), ("A", 0)])
def test_rls_shows_a_reply_to_its_crew_member_and_the_dispatcher(client, world, user, seen):
    message = send(client, world, "C").json()["id"]
    reply(client, world, message)

    async def count(conn):
        return await conn.fetchval(
            "select count(*) from public.message_replies where crew_message_id = $1",
            UUID(message),
        )

    assert as_role(world, user, count) == seen


def test_nobody_edits_or_deletes_a_reply(client, world):
    message = send(client, world, "C").json()["id"]
    reply(client, world, message)
    for query in [
        "update public.message_replies set preset_message_id = preset_message_id",
        "delete from public.message_replies",
    ]:

        async def attempt(conn, query=query):
            await conn.execute(query)

        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            as_role(world, "D", attempt)
