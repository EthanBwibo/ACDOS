"""Crew-to-dispatcher preset messages (#54, minimal).

Crew send one of a fixed set of presets; every message goes to the
dispatcher, who reads them and marks them read. No free text, no crew-to-
crew or crew-to-driver channel: drivers get 403 on every route here. The
caller's role comes from profiles.role (#127); rows are filtered by RLS
(migration 028, app/reads.py).

Messages never trigger re-optimisation: nothing in this router creates an
optimisation job. The dispatcher decides, and starts one with POST
/optimisation-jobs.
"""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, status

from app import dispatch, messages, reads
from app.auth import CallerDep
from app.errors import ApiError, ErrorCode, errors
from app.models.schemas import (
    CrewMessage,
    CrewMessageCreate,
    CrewMessagePage,
    CrewMessageRead,
    PresetMessageList,
)

router = APIRouter(tags=["messages"])

PAGE_SIZE = 20
MAX_PAGE_SIZE = 50

_CALLER_ERRORS = {
    401: [ErrorCode.UNAUTHORIZED],
    403: [ErrorCode.FORBIDDEN],
    503: [ErrorCode.UNAVAILABLE],
}


def _require(profile: reads.Profile | None, *roles: str) -> reads.Profile:
    if profile is None or profile.role not in roles:
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            ErrorCode.FORBIDDEN,
            f"only {' or '.join(roles)} may use this",
        )
    return profile


@router.get("/preset-messages", response_model=PresetMessageList, responses=errors(_CALLER_ERRORS))
async def list_presets(request: Request, caller: CallerDep) -> PresetMessageList:
    """The presets crew may send. A fixed set, so not paginated."""
    async with reads.as_caller(reads.pool(request), caller.user_id) as (conn, profile):
        _require(profile, "crew", "dispatcher")
        return PresetMessageList(items=await messages.presets(conn))


@router.post(
    "/messages",
    response_model=CrewMessage,
    responses=errors(
        _CALLER_ERRORS | {422: [ErrorCode.VALIDATION_FAILED, ErrorCode.IDEMPOTENCY_KEY_REUSED]}
    ),
)
async def send_message(
    request: Request,
    caller: CallerDep,
    body: CrewMessageCreate,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)],
) -> CrewMessage:
    """Crew send a preset to the dispatcher. Safe to retry with the same
    Idempotency-Key: the retry gets the message already sent."""
    async with reads.as_caller(reads.pool(request), caller.user_id) as (conn, profile):
        profile = _require(profile, "crew")
        if profile.crew_member_id is None:
            raise ApiError(
                status.HTTP_403_FORBIDDEN,
                ErrorCode.FORBIDDEN,
                "this crew account has no crew record yet",
            )
        try:
            return await messages.send(
                conn, profile.crew_member_id, body.preset_code, idempotency_key
            )
        except messages.UnknownPreset as error:
            raise ApiError(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                ErrorCode.VALIDATION_FAILED,
                f"no preset message {body.preset_code!r}; GET /preset-messages lists them",
            ) from error
        except messages.KeyReused as error:
            raise ApiError(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                ErrorCode.IDEMPOTENCY_KEY_REUSED,
                "this Idempotency-Key was used for another message",
            ) from error


@router.get(
    "/messages",
    response_model=CrewMessagePage,
    responses=errors(_CALLER_ERRORS | {422: [ErrorCode.VALIDATION_FAILED]}),
)
async def list_messages(
    request: Request,
    caller: CallerDep,
    unread: bool = False,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = PAGE_SIZE,
) -> CrewMessagePage:
    """Newest first. Crew get their own; the dispatcher gets every crew
    member's, ?unread=true for those not yet read."""
    try:
        after = dispatch.time_key(cursor)
    except ValueError as error:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorCode.VALIDATION_FAILED, "invalid cursor"
        ) from error
    async with reads.as_caller(reads.pool(request), caller.user_id) as (conn, profile):
        profile = _require(profile, "crew", "dispatcher")
        if profile.role == "crew" and profile.crew_member_id is None:
            return CrewMessagePage(items=[], next_cursor=None)
        # Crew are filtered to themselves explicitly as well as by RLS.
        own = profile.crew_member_id if profile.role == "crew" else None
        return await messages.page(conn, own, unread, after, limit)


@router.post(
    "/messages/{message_id}/ack",
    response_model=CrewMessageRead,
    responses=errors(
        _CALLER_ERRORS | {404: [ErrorCode.NOT_FOUND], 422: [ErrorCode.VALIDATION_FAILED]}
    ),
)
async def ack_message(request: Request, caller: CallerDep, message_id: UUID) -> CrewMessageRead:
    """The dispatcher has read a message. Safe to retry: the first time
    stands."""
    async with reads.as_caller(reads.pool(request), caller.user_id) as (conn, profile):
        _require(profile, "dispatcher")
        read_at = await messages.mark_read(conn, message_id, datetime.now(UTC))
    if read_at is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "no such message")
    return CrewMessageRead(id=message_id, read_at=read_at)
