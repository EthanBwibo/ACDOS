"""The driver's pickup events, uploaded from the app's outbox (#33).

POST a batch; get one result per event, in request order (app/events.py).
The whole request fails only for no or a bad token (401), not a driver (403),
a body over BODY_LIMIT bytes (413, app/body_limit.py), a malformed batch
(422) or no database (503); otherwise it is 200 and each event says what
became of it.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Request, status

from app import events, reads
from app.auth import CallerDep
from app.errors import ApiError, ErrorCode, errors
from app.models.schemas import PickupEventBatch, PickupEventResults

router = APIRouter(tags=["me"])

PATH = "/drivers/me/pickup-events"
# 50 events of about 250 bytes each, with room to spare: about 10 s on a
# poor 2G link.
BODY_LIMIT = 32 * 1024


@router.post(
    PATH,
    response_model=PickupEventResults,
    response_model_exclude_none=True,
    responses=errors(
        {
            401: [ErrorCode.UNAUTHORIZED],
            403: [ErrorCode.FORBIDDEN],
            413: [ErrorCode.PAYLOAD_TOO_LARGE],
            422: [ErrorCode.VALIDATION_FAILED],
            503: [ErrorCode.UNAVAILABLE],
        }
    ),
)
async def upload(
    request: Request, caller: CallerDep, batch: PickupEventBatch
) -> PickupEventResults:
    pool = reads.pool(request)
    profile = await reads.profile_of(pool, caller.user_id)
    if profile is None or profile.role != "driver":
        raise ApiError(
            status.HTTP_403_FORBIDDEN, ErrorCode.FORBIDDEN, "only a driver may upload pickup events"
        )
    results = await events.record(pool, caller.user_id, batch.events, datetime.now(UTC))
    return PickupEventResults(results=results)
