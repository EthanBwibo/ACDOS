"""The dispatcher's dashboard (#136, for Android #27).

Only dispatchers may call these: the caller's token is checked
(app/auth.py, 401 without a valid one), and their profiles.role must be
dispatcher (403 otherwise), as for the job API (#127). Everything runs
under the caller's RLS (app/reads.py), the updates included; the queries
are in app/dispatch.py.

The two PATCHes only record a change. Neither starts a re-plan: the
dispatcher does that with POST /optimisation-jobs, choosing the trigger
(flight_delay after a new report time, vehicle_breakdown after a van is set
broken_down). Both are safe to retry: they set a value, so a repeat leaves
the same row.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, status

from app import dispatch, reads
from app.auth import CallerDep
from app.config import settings
from app.errors import ApiError, ErrorCode, errors
from app.models.schemas import (
    DispatcherPickup,
    DispatcherPickupPage,
    DispatcherRoutePage,
    DispatcherVehicle,
    DispatcherVehiclePage,
    PickupReportTimeUpdate,
    VehicleStatusUpdate,
)

router = APIRouter(tags=["dispatcher"])

PAGE_SIZE = 20
MAX_PAGE_SIZE = 50

_CALLER_ERRORS = {
    401: [ErrorCode.UNAUTHORIZED],
    403: [ErrorCode.FORBIDDEN],
    503: [ErrorCode.UNAVAILABLE],
}
_LIST_ERRORS = _CALLER_ERRORS | {422: [ErrorCode.VALIDATION_FAILED]}

Limit = Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)]
# A Nairobi calendar day; today in Nairobi when left out.
Day = Annotated[
    date | None, Query(alias="date", description="YYYY-MM-DD, Nairobi time; default today")
]


def _dispatcher_only(profile: reads.Profile | None) -> None:
    if profile is None or profile.role != "dispatcher":
        raise ApiError(
            status.HTTP_403_FORBIDDEN, ErrorCode.FORBIDDEN, "only a dispatcher may use this"
        )


def _day(day: date | None) -> date:
    return day or datetime.now(dispatch.EAT).date()


def _bad_cursor() -> ApiError:
    return ApiError(
        status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorCode.VALIDATION_FAILED, "invalid cursor"
    )


def _grace() -> timedelta:
    return timedelta(minutes=settings.van_return_grace_min)


@router.get("/pickup-requests", response_model=DispatcherPickupPage, responses=errors(_LIST_ERRORS))
async def list_pickups(
    request: Request,
    caller: CallerDep,
    day: Day = None,
    cursor: str | None = None,
    limit: Limit = PAGE_SIZE,
) -> DispatcherPickupPage:
    """The pickups reporting on a day, in report-time order."""
    try:
        after = dispatch.time_key(cursor)
    except ValueError as error:
        raise _bad_cursor() from error
    async with reads.as_caller(reads.pool(request), caller.user_id) as (conn, profile):
        _dispatcher_only(profile)
        return await dispatch.pickup_page(conn, _day(day), after, limit)


@router.patch(
    "/pickup-requests/{pickup_id}",
    response_model=DispatcherPickup,
    responses=errors(
        _CALLER_ERRORS
        | {
            404: [ErrorCode.NOT_FOUND],
            422: [ErrorCode.VALIDATION_FAILED, ErrorCode.NOT_PLANNABLE],
        }
    ),
)
async def set_report_time(
    request: Request, caller: CallerDep, pickup_id: UUID, body: PickupReportTimeUpdate
) -> DispatcherPickup:
    """Record a new report time (a flight delay). Starts no re-plan."""
    async with reads.as_caller(reads.pool(request), caller.user_id) as (conn, profile):
        _dispatcher_only(profile)
        result = await dispatch.update_report_time(conn, pickup_id, body.report_time)
    if result is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "no such pickup request")
    if isinstance(result, str):
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ErrorCode.NOT_PLANNABLE,
            f"this pickup is {result}: its report time no longer changes anything",
            pickup_request_ids=[pickup_id],
        )
    return result


@router.get("/vehicles", response_model=DispatcherVehiclePage, responses=errors(_LIST_ERRORS))
async def list_vehicles(
    request: Request, caller: CallerDep, cursor: str | None = None, limit: Limit = PAGE_SIZE
) -> DispatcherVehiclePage:
    """Every vehicle, in plate order, with whether it is on the road."""
    try:
        after = dispatch.decode_cursor(cursor) if cursor else None
    except ValueError as error:
        raise _bad_cursor() from error
    async with reads.as_caller(reads.pool(request), caller.user_id) as (conn, profile):
        _dispatcher_only(profile)
        return await dispatch.vehicle_page(conn, after, limit, datetime.now(UTC), _grace())


@router.patch(
    "/vehicles/{vehicle_id}",
    response_model=DispatcherVehicle,
    responses=errors(
        _CALLER_ERRORS | {404: [ErrorCode.NOT_FOUND], 422: [ErrorCode.VALIDATION_FAILED]}
    ),
)
async def set_vehicle_status(
    request: Request, caller: CallerDep, vehicle_id: UUID, body: VehicleStatusUpdate
) -> DispatcherVehicle:
    """Set a vehicle's status, e.g. broken_down. Starts no re-plan."""
    async with reads.as_caller(reads.pool(request), caller.user_id) as (conn, profile):
        _dispatcher_only(profile)
        vehicle = await dispatch.update_vehicle_status(
            conn, vehicle_id, body.status, datetime.now(UTC), _grace()
        )
    if vehicle is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "no such vehicle")
    return vehicle


@router.get("/routes", response_model=DispatcherRoutePage, responses=errors(_LIST_ERRORS))
async def list_routes(
    request: Request,
    caller: CallerDep,
    day: Day = None,
    cursor: str | None = None,
    limit: Limit = PAGE_SIZE,
) -> DispatcherRoutePage:
    """The active routes leaving the depot on a day, with their live stops."""
    try:
        after = dispatch.time_key(cursor)
    except ValueError as error:
        raise _bad_cursor() from error
    async with reads.as_caller(reads.pool(request), caller.user_id) as (conn, profile):
        _dispatcher_only(profile)
        return await dispatch.route_page(conn, _day(day), after, limit)
