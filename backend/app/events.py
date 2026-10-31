"""Recording a driver's pickup events from the app's outbox (#33).

Each event is handled on its own, in request order, in its own transaction,
so one bad event never loses the others, and a no_show then a later
pickup_confirmed for the same stop apply in that order. Each gets a result
the outbox acts on:

- accepted:  stored now. stop_replanned when the stop was superseded by a
             later plan after the event happened (#113 handles that).
- duplicate: already stored with the same fields (a resend): counts as
             success.
- rejected:  final, with an ErrorCode; resending will not change it.

Checks, in order:
1. exception_type present exactly for exceptions; occurred_at not more than
   FUTURE_SKEW ahead of the server (validation_failed). Offline events arrive
   late, so a past occurred_at is never refused for its age.
2. driver_id is the caller (driver_mismatch).
3. The key: earlier in this batch, or already stored (read as postgres:
   drivers cannot read pickup_events). Same fields: duplicate; different
   fields or another driver's: idempotency_key_reused.
4. Insert as the caller, under real RLS (reads.become): the insert policy
   (migration 022) decides whether the stop was the driver's when the event
   happened (not_your_stop), the one-confirmation index refuses a second
   confirmation of a node (already_confirmed), and the trigger from 023
   moves the pickup's status in the same transaction.
"""

from datetime import datetime, timedelta
from uuid import UUID

import asyncpg

from app import reads
from app.errors import ErrorCode
from app.models.schemas import (
    PickupEventIn,
    PickupEventOutcome,
    PickupEventResult,
    PickupEventType,
)

# How far ahead of the server a device clock may be.
FUTURE_SKEW = timedelta(minutes=5)

ONE_CONFIRMATION_INDEX = "pickup_events_one_confirmation_per_node"

_STORED = """
    select id, route_node_id, driver_id, event_type, exception_type, confirmed_at
    from public.pickup_events
    where idempotency_key = $1
"""


def _accepted(event: PickupEventIn, event_id: UUID, replanned: bool) -> PickupEventResult:
    return PickupEventResult(
        idempotency_key=event.idempotency_key,
        status=PickupEventOutcome.ACCEPTED,
        event_id=event_id,
        stop_replanned=True if replanned else None,
    )


def _duplicate(event: PickupEventIn, event_id: UUID) -> PickupEventResult:
    return PickupEventResult(
        idempotency_key=event.idempotency_key,
        status=PickupEventOutcome.DUPLICATE,
        event_id=event_id,
    )


def _rejected(event: PickupEventIn, code: ErrorCode, detail: str) -> PickupEventResult:
    return PickupEventResult(
        idempotency_key=event.idempotency_key,
        status=PickupEventOutcome.REJECTED,
        code=code,
        detail=detail,
    )


def _fields(event: PickupEventIn) -> tuple:
    return (
        event.route_node_id,
        event.driver_id,
        event.event_type.value,
        event.exception_type.value if event.exception_type else None,
        event.occurred_at,
    )


def _against_stored(event: PickupEventIn, stored: asyncpg.Record) -> PickupEventResult:
    """The key is already stored: a resend, or the key used for something
    else (never saying which, or whose)."""
    if tuple(stored)[1:] == _fields(event):
        return _duplicate(event, stored["id"])
    return _rejected(
        event,
        ErrorCode.IDEMPOTENCY_KEY_REUSED,
        "this idempotency_key was already used for a different event",
    )


def _invalid(event: PickupEventIn, now: datetime) -> str | None:
    is_exception = event.event_type == PickupEventType.EXCEPTION
    if is_exception and event.exception_type is None:
        return "an exception needs an exception_type"
    if not is_exception and event.exception_type is not None:
        return "only an exception has an exception_type"
    if event.occurred_at > now + FUTURE_SKEW:
        return "occurred_at is in the future"
    return None


async def record(
    pool: asyncpg.Pool, driver_id: UUID, events: list[PickupEventIn], now: datetime
) -> list[PickupEventResult]:
    results: list[PickupEventResult] = []
    earlier: dict[str, tuple[PickupEventIn, PickupEventResult]] = {}
    for event in events:
        key = event.idempotency_key
        if key in earlier:
            first, first_result = earlier[key]
            if _fields(first) != _fields(event):
                result = _rejected(
                    event,
                    ErrorCode.IDEMPOTENCY_KEY_REUSED,
                    "this idempotency_key is used for a different event earlier in the batch",
                )
            elif first_result.status == PickupEventOutcome.REJECTED:
                result = first_result  # the same event, so the same answer
            else:
                result = _duplicate(event, first_result.event_id)
        else:
            result = await _record_one(pool, driver_id, event, now)
            earlier[key] = (event, result)
        results.append(result)
    return results


async def _record_one(
    pool: asyncpg.Pool, driver_id: UUID, event: PickupEventIn, now: datetime
) -> PickupEventResult:
    problem = _invalid(event, now)
    if problem:
        return _rejected(event, ErrorCode.VALIDATION_FAILED, problem)
    if event.driver_id != driver_id:
        return _rejected(event, ErrorCode.DRIVER_MISMATCH, "driver_id is not the signed-in driver")

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():
                # As postgres, before switching to the caller.
                stored = await conn.fetchrow(_STORED, event.idempotency_key)
                if stored is not None:
                    return _against_stored(event, stored)
                superseded_at = await conn.fetchval(
                    "select superseded_at from public.route_nodes where id = $1",
                    event.route_node_id,
                )
                await reads.become(conn, driver_id)
                event_id = await conn.fetchval(
                    """
                    insert into public.pickup_events (route_node_id, driver_id, event_type,
                        exception_type, confirmed_at, synced_at, idempotency_key)
                    values ($1, $2, $3, $4, $5, $6, $7)
                    returning id
                    """,
                    *_fields(event),
                    now,
                    event.idempotency_key,
                )
            return _accepted(event, event_id, replanned=superseded_at is not None)
        except asyncpg.InsufficientPrivilegeError:
            # The insert policy (022): not this driver's stop when it happened.
            return _rejected(
                event,
                ErrorCode.NOT_YOUR_STOP,
                "this stop was not on your route when the event happened",
            )
        except asyncpg.UniqueViolationError as error:
            if error.constraint_name == ONE_CONFIRMATION_INDEX:
                return _rejected(
                    event, ErrorCode.ALREADY_CONFIRMED, "this stop is already confirmed"
                )
            # The key, stored by a concurrent request since the lookup above.
            stored = await conn.fetchrow(_STORED, event.idempotency_key)
            if stored is None:
                raise
            return _against_stored(event, stored)
