"""The dispatcher's dashboard (#136, for Android #27).

Only dispatchers may call these: the caller's token is checked
(app/auth.py, 401 without a valid one), and their profiles.role must be
dispatcher (403 otherwise), as for the job API (#127). Everything runs
under the caller's RLS (app/reads.py), the updates included; the queries
are in app/dispatch.py.

POST /roster-imports (#229) puts crew and their pickups in from the
roster CSV (app/roster.py). It starts no re-plan either.

Add pickup and Set home (#253) do the same for one pickup or one home,
without a CSV: POST /pickup-requests and PATCH /crew-members/{id}/home
reject what the import rejects, with its reasons as the error codes
(app/manual.py). GET /crew-members finds crew for them, and GET
/pickup-zones/nearest gives a map pin's zone, once per placement.

The two PATCHes only record a change. Neither starts a re-plan: the
dispatcher does that with POST /optimisation-jobs, choosing the trigger
(flight_delay after a new report time, vehicle_breakdown after a van is set
broken_down). Both are safe to retry: they set a value, so a repeat leaves
the same row.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Header, Query, Request, UploadFile, status

from app import dispatch, manual, reads, roster
from app.auth import CallerDep
from app.config import settings
from app.errors import ApiError, ErrorCode, errors
from app.models.schemas import (
    CrewHome,
    CrewListPage,
    DispatcherPickup,
    DispatcherPickupPage,
    DispatcherRoutePage,
    DispatcherVehicle,
    DispatcherVehiclePage,
    LatLon,
    NearestZone,
    PickupReportTimeUpdate,
    PickupRequestCreate,
    RosterImportResult,
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


ROSTER_IMPORTS = "/roster-imports"


@router.post(
    ROSTER_IMPORTS,
    response_model=RosterImportResult,
    responses=errors(
        _CALLER_ERRORS
        | {
            413: [ErrorCode.PAYLOAD_TOO_LARGE],
            422: [ErrorCode.VALIDATION_FAILED, ErrorCode.IDEMPOTENCY_KEY_REUSED],
        }
    ),
)
async def import_roster(
    request: Request,
    caller: CallerDep,
    file: Annotated[
        UploadFile,
        File(description="The roster CSV (docs/roster_import.md, docs/acdos_roster_template.csv)"),
    ],
    dry_run: bool = False,
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key", min_length=1, max_length=200)
    ] = None,
) -> RosterImportResult:
    """Import crew and their pickups from a roster CSV of up to 500 rows.
    Headers ignore case, spaces, underscores and hyphens, and accept common
    aliases (role, location, report, ...); a missing column is named in the
    error with the headers found.
    Rejected rows are skipped and listed with their line and reason; the rest
    import together. With dry_run=true nothing is written: the result is what
    the import would do. A real import needs an Idempotency-Key: a retry with
    the same key and file gets the first result and imports nothing. Starts
    no re-plan."""
    if not dry_run and idempotency_key is None:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ErrorCode.VALIDATION_FAILED,
            "header.idempotency-key: a real import needs one (a dry run doesn't)",
        )
    content = await file.read()
    async with reads.as_caller(reads.pool(request), caller.user_id) as (conn, profile):
        _dispatcher_only(profile)
        try:
            return await roster.run(
                conn,
                content,
                datetime.now(UTC),
                dry_run=dry_run,
                idempotency_key=idempotency_key,
                dispatcher_id=caller.user_id,
            )
        except roster.BadFile as error:
            raise ApiError(
                status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorCode.VALIDATION_FAILED, str(error)
            ) from error
        except roster.KeyReused as error:
            raise ApiError(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                ErrorCode.IDEMPOTENCY_KEY_REUSED,
                "this Idempotency-Key already imported a different file",
            ) from error


# The import's reject reasons, as error codes (#253).
_REJECTIONS = [
    ErrorCode.OUTSIDE_PICKUP_ZONES,
    ErrorCode.REPORT_TIME_PAST,
    ErrorCode.DUPLICATE_PICKUP,
    ErrorCode.NO_PICKUP_LOCATION,
]
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)]


def _rejected(error: manual.Rejected) -> ApiError:
    return ApiError(status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorCode(error.reason), error.detail)


@router.get("/crew-members", response_model=CrewListPage, responses=errors(_LIST_ERRORS))
async def list_crew(
    request: Request,
    caller: CallerDep,
    q: Annotated[
        str | None, Query(max_length=100, description="part of a name or staff number")
    ] = None,
    cursor: str | None = None,
    limit: Limit = PAGE_SIZE,
) -> CrewListPage:
    """Crew in name order, optionally only those whose name or staff number
    contains q (ignoring case)."""
    try:
        after = dispatch.decode_cursor(cursor) if cursor else None
    except ValueError as error:
        raise _bad_cursor() from error
    async with reads.as_caller(reads.pool(request), caller.user_id) as (conn, profile):
        _dispatcher_only(profile)
        return await manual.crew_page(conn, (q or "").strip(), after, limit)


@router.get("/pickup-zones/nearest", response_model=NearestZone, responses=errors(_LIST_ERRORS))
async def nearest_zone(
    request: Request,
    caller: CallerDep,
    lat: Annotated[float, Query(ge=-90, le=90)],
    lon: Annotated[float, Query(ge=-180, le=180)],
) -> NearestZone:
    """A map pin's nearest pickup zone and whether it can be saved: the
    import's zone check. Call it when the pin is placed, not while dragging."""
    async with reads.as_caller(reads.pool(request), caller.user_id) as (conn, profile):
        _dispatcher_only(profile)
        return await manual.nearest_zone(conn, LatLon(lat=lat, lon=lon))


@router.post(
    "/pickup-requests",
    status_code=status.HTTP_201_CREATED,
    response_model=DispatcherPickup,
    responses=errors(
        _CALLER_ERRORS
        | {
            404: [ErrorCode.NOT_FOUND],
            422: [ErrorCode.VALIDATION_FAILED, ErrorCode.IDEMPOTENCY_KEY_REUSED, *_REJECTIONS],
        }
    ),
)
async def add_pickup(
    request: Request,
    caller: CallerDep,
    body: PickupRequestCreate,
    idempotency_key: IdempotencyKey,
) -> DispatcherPickup:
    """Add one pending pickup, at pickup_location or else the crew member's
    home. Rejected for the import's reasons. A retry with the same key and
    body returns the same pickup; the same key with another body is
    idempotency_key_reused. Starts no re-plan."""
    async with reads.as_caller(reads.pool(request), caller.user_id) as (conn, profile):
        _dispatcher_only(profile)
        try:
            pickup = await manual.add_pickup(conn, body, idempotency_key, datetime.now(UTC))
        except manual.Rejected as error:
            raise _rejected(error) from error
        except manual.KeyReused as error:
            raise ApiError(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                ErrorCode.IDEMPOTENCY_KEY_REUSED,
                "this Idempotency-Key already added a different pickup",
            ) from error
    if pickup is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "no such crew member")
    return pickup


@router.patch(
    "/crew-members/{crew_member_id}/home",
    response_model=CrewHome,
    responses=errors(
        _CALLER_ERRORS
        | {
            404: [ErrorCode.NOT_FOUND],
            422: [ErrorCode.VALIDATION_FAILED, ErrorCode.OUTSIDE_PICKUP_ZONES],
        }
    ),
)
async def set_home(
    request: Request, caller: CallerDep, crew_member_id: UUID, body: LatLon
) -> CrewHome:
    """Move a crew member's home to the point, from now on: pickups already
    stored keep their points. Rejected beyond 10 km of every zone, as in the
    import. Safe to retry. Starts no re-plan."""
    async with reads.as_caller(reads.pool(request), caller.user_id) as (conn, profile):
        _dispatcher_only(profile)
        try:
            home = await manual.set_home(conn, crew_member_id, body)
        except manual.Rejected as error:
            raise _rejected(error) from error
    if home is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "no such crew member")
    return home
