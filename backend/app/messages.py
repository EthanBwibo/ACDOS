"""Preset messages between crew and the dispatcher (#54).

Every function takes a connection already running as the caller
(reads.as_caller), so RLS applies (migration 028); the router checks the
role first. Nothing here touches optimisation jobs: messages never trigger
re-optimisation (CLAUDE.md).
"""

from datetime import datetime
from uuid import UUID

import asyncpg

from app.dispatch import encode_cursor
from app.models.schemas import CrewMessage, CrewMessagePage, MessageReply, PresetMessage

# One message with what both screens show.
_MESSAGES = """
    select m.id, m.crew_member_id, c.name as crew_name, p.code, p.label,
        m.sent_at, m.read_at
    from public.crew_messages m
    join public.crew_members c on c.id = m.crew_member_id
    join public.preset_messages p on p.id = m.preset_message_id
"""


# One reply with what both screens show.
_REPLIES = """
    select r.id, r.crew_message_id, p.code, p.label, r.sent_at
    from public.message_replies r
    join public.preset_messages p on p.id = r.preset_message_id
"""


def _reply(row: asyncpg.Record) -> MessageReply:
    return MessageReply(
        id=row["id"], preset_code=row["code"], label=row["label"], sent_at=row["sent_at"]
    )


async def _with_replies(conn: asyncpg.Connection, rows: list[asyncpg.Record]) -> list[CrewMessage]:
    """One query for the page's replies, not one per message."""
    replies = await conn.fetch(
        f"{_REPLIES} where r.crew_message_id = any($1) order by r.sent_at, r.id",
        [r["id"] for r in rows],
    )
    by_message: dict[UUID, list[MessageReply]] = {}
    for reply in replies:
        by_message.setdefault(reply["crew_message_id"], []).append(_reply(reply))
    return [_message(r, by_message.get(r["id"], [])) for r in rows]


def _message(row: asyncpg.Record, replies: list[MessageReply]) -> CrewMessage:
    return CrewMessage(
        id=row["id"],
        crew_member_id=row["crew_member_id"],
        crew_name=row["crew_name"],
        preset_code=row["code"],
        label=row["label"],
        sent_at=row["sent_at"],
        read_at=row["read_at"],
        replies=replies,
    )


async def presets(conn: asyncpg.Connection, sender: str) -> list[PresetMessage]:
    """The presets [sender], 'crew' or 'dispatcher', may send."""
    rows = await conn.fetch(
        "select code, label from public.preset_messages where sender = $1 order by code", sender
    )
    return [PresetMessage(code=r["code"], label=r["label"]) for r in rows]


class UnknownPreset(Exception):
    pass


class UnknownMessage(Exception):
    pass


class KeyReused(Exception):
    """The Idempotency-Key already sent a different message (or one that is
    not the caller's)."""


async def send(
    conn: asyncpg.Connection, crew_member_id: UUID, preset_code: str, idempotency_key: str
) -> CrewMessage:
    """Send a preset to the dispatcher, once per Idempotency-Key: a retry
    with the same key and preset gets the message it already sent."""
    preset = await conn.fetchval(
        "select id from public.preset_messages where code = $1 and sender = 'crew'", preset_code
    )
    if preset is None:
        raise UnknownPreset(preset_code)
    message = await conn.fetchval(
        """
        insert into public.crew_messages (crew_member_id, preset_message_id, idempotency_key)
        values ($1, $2, $3)
        on conflict (idempotency_key) do nothing
        returning id
        """,
        crew_member_id,
        preset,
        idempotency_key,
    )
    if message is None:
        # Under RLS only the caller's own messages are visible, so another
        # crew member's key reads as none here.
        earlier = await conn.fetchrow(
            "select id, preset_message_id from public.crew_messages where idempotency_key = $1",
            idempotency_key,
        )
        if earlier is None or earlier["preset_message_id"] != preset:
            raise KeyReused(idempotency_key)
        message = earlier["id"]
    return (
        await _with_replies(conn, [await conn.fetchrow(f"{_MESSAGES} where m.id = $1", message)])
    )[0]


async def reply(
    conn: asyncpg.Connection,
    message_id: UUID,
    dispatcher_id: UUID,
    preset_code: str,
    idempotency_key: str,
    now: datetime,
) -> MessageReply:
    """Reply to a crew message with a preset, once per Idempotency-Key.
    Replying means the dispatcher has read it, so the message is marked read.
    Nothing here touches optimisation jobs."""
    preset = await conn.fetchval(
        "select id from public.preset_messages where code = $1 and sender = 'dispatcher'",
        preset_code,
    )
    if preset is None:
        raise UnknownPreset(preset_code)
    if await mark_read(conn, message_id, now) is None:
        raise UnknownMessage(message_id)
    reply_id = await conn.fetchval(
        """
        insert into public.message_replies
            (crew_message_id, preset_message_id, dispatcher_id, idempotency_key)
        values ($1, $2, $3, $4)
        on conflict (idempotency_key) do nothing
        returning id
        """,
        message_id,
        preset,
        dispatcher_id,
        idempotency_key,
    )
    if reply_id is None:
        earlier = await conn.fetchrow(
            "select id, crew_message_id, preset_message_id from public.message_replies "
            "where idempotency_key = $1",
            idempotency_key,
        )
        if (
            earlier is None
            or earlier["crew_message_id"] != message_id
            or earlier["preset_message_id"] != preset
        ):
            raise KeyReused(idempotency_key)
        reply_id = earlier["id"]
    return _reply(await conn.fetchrow(f"{_REPLIES} where r.id = $1", reply_id))


async def page(
    conn: asyncpg.Connection,
    crew_member_id: UUID | None,
    unread_only: bool,
    after: tuple[datetime, UUID] | None,
    limit: int,
) -> CrewMessagePage:
    """Messages newest first: one crew member's (crew_member_id), or every
    one (None, for the dispatcher). Keyset paginated on (sent_at, id)."""
    rows = await conn.fetch(
        f"""
        select * from ({_MESSAGES}) d
        where ($1::uuid is null or crew_member_id = $1)
          and (not $2 or read_at is null)
          and ($3::timestamptz is null or (sent_at, id) < ($3, $4))
        order by sent_at desc, id desc
        limit $5
        """,
        crew_member_id,
        unread_only,
        after[0] if after else None,
        after[1] if after else None,
        limit + 1,
    )
    more = len(rows) > limit
    rows = rows[:limit]
    return CrewMessagePage(
        items=await _with_replies(conn, rows),
        next_cursor=(
            encode_cursor(rows[-1]["sent_at"].isoformat(), rows[-1]["id"]) if more else None
        ),
    )


async def mark_read(conn: asyncpg.Connection, message_id: UUID, now: datetime) -> datetime | None:
    """Mark a message read; when it first was, on a retry too. None if there
    is no such message."""
    row = await conn.fetchrow(
        """
        update public.crew_messages set read_at = coalesce(read_at, $2)
        where id = $1
        returning read_at
        """,
        message_id,
        now,
    )
    return row["read_at"] if row else None
