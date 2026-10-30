"""The signed-in driver's and crew member's own data (#52).

Who the caller is comes from their verified token (app/auth.py); what they
are comes from profiles.role. A request never names a user or a role. The
rows themselves are filtered by RLS (app/reads.py).
"""

from datetime import UTC, datetime
from typing import Annotated

import asyncpg
from fastapi import APIRouter, HTTPException, Query, Request, status

from app import reads
from app.auth import CallerDep
from app.models.schemas import CrewPickupResponse, DriverRouteResponse, RouteSummaryPage

router = APIRouter(tags=["me"])

PAGE_SIZE = 20
MAX_PAGE_SIZE = 50


def _db(request: Request) -> asyncpg.Pool:
    pool = getattr(request.app.state, "db", None)
    if pool is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "DATABASE_URL is not set")
    return pool


def _require(profile: reads.Profile | None, role: str) -> None:
    if profile is None or profile.role != role:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"only a {role} may read this")


@router.get("/drivers/me/route", response_model=DriverRouteResponse)
async def my_route(request: Request, caller: CallerDep) -> DriverRouteResponse:
    async with reads.as_caller(_db(request), caller.user_id) as (conn, profile):
        _require(profile, "driver")
        return DriverRouteResponse(route=await reads.current_route(conn, caller.user_id))


@router.get("/drivers/me/routes", response_model=RouteSummaryPage)
async def my_routes(
    request: Request,
    caller: CallerDep,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = PAGE_SIZE,
) -> RouteSummaryPage:
    try:
        after = reads.decode_cursor(cursor) if cursor else None
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid cursor") from error
    async with reads.as_caller(_db(request), caller.user_id) as (conn, profile):
        _require(profile, "driver")
        return await reads.route_page(conn, caller.user_id, after, limit)


@router.get("/crew/me/pickup", response_model=CrewPickupResponse)
async def my_pickup(request: Request, caller: CallerDep) -> CrewPickupResponse:
    async with reads.as_caller(_db(request), caller.user_id) as (conn, profile):
        _require(profile, "crew")
        if profile.crew_member_id is None:
            # A crew account not yet linked to a crew_members row.
            return CrewPickupResponse(pickup=None)
        pickup = await reads.next_pickup(conn, profile.crew_member_id, datetime.now(UTC))
        return CrewPickupResponse(pickup=pickup)
