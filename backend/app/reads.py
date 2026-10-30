"""Reads for the driver and crew screens (#52), under the caller's RLS.

The backend connects as postgres, which bypasses RLS. These reads must not:
each runs in one transaction that first looks up who the caller is (as
postgres, for the 403 check and the explicit filters below), then switches
to the caller with

    SET LOCAL ROLE authenticated;
    set_config('request.jwt.claim.sub', <sub>, true)
    set_config('request.jwt.claims', {"sub": ..., "role": "authenticated"}, true)

which is what Supabase's auth.uid() reads, so the policies in 011, 012, 018,
020 and 021 filter every row from then on. Both are transaction-local, so
the pooled connection goes back clean. Every query also filters by the
caller itself: a second check, so a policy mistake cannot widen what a user
sees on its own.

Every name is schema-qualified, PostGIS included (extensions).
"""

import base64
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import asyncpg

from app.models.schemas import (
    CrewPickup,
    DriverRoute,
    DriverStop,
    RouteSummary,
    RouteSummaryPage,
)

# Stop coordinates for the driver's navigation: 5 decimal places is about
# 1 m, enough to navigate by, and keeps the payload small on 2G.
COORDINATE_DECIMALS = 5


@dataclass(frozen=True)
class Profile:
    role: str
    crew_member_id: UUID | None  # set only for crew with a crew_members row


@asynccontextmanager
async def as_caller(
    pool: asyncpg.Pool, user_id: UUID
) -> AsyncIterator[tuple[asyncpg.Connection, Profile | None]]:
    """A transaction running as the caller, and their profile (None when
    they have no profiles row)."""
    async with pool.acquire() as conn, conn.transaction():
        row = await conn.fetchrow(
            """
            select p.role, c.id as crew_member_id
            from public.profiles p
            left join public.crew_members c on c.profile_id = p.id
            where p.id = $1
            """,
            user_id,
        )
        profile = Profile(row["role"], row["crew_member_id"]) if row else None
        await become(conn, user_id)
        yield conn, profile


async def become(conn: asyncpg.Connection, user_id: UUID) -> None:
    """Run the rest of conn's transaction as the user, under RLS. Must be
    inside a transaction: both settings end with it."""
    await conn.execute("set local role authenticated")
    await conn.execute(
        """
        select set_config('request.jwt.claim.sub', $1, true),
               set_config('request.jwt.claims', $2, true)
        """,
        str(user_id),
        json.dumps({"sub": str(user_id), "role": "authenticated"}),
    )


# The stops of one route ($1), live only, in order, with what the driver's
# screen shows. The zone is the nearest of pickup_zones by PostGIS.
_STOPS = """
    select n.id as route_node_id, n.seq_order, n.estimated_arrival,
        c.name as crew_name,
        z.label as zone_label,
        extensions.st_y(p.pickup_location::extensions.geometry) as lat,
        extensions.st_x(p.pickup_location::extensions.geometry) as lon
    from public.route_nodes n
    join public.pickup_requests p on p.id = n.pickup_request_id
    join public.crew_members c on c.id = p.crew_member_id
    left join lateral (
        select label from public.pickup_zones
        order by extensions.st_distance(location, p.pickup_location)
        limit 1
    ) z on true
    where n.route_id = $1 and n.superseded_at is null
    order by n.seq_order
"""

# The caller's ($1) active routes, each with its first live stop's time.
# The join on assigned_driver_id is the explicit second check.
_DRIVER_ROUTES = """
    select r.id, r.status, r.total_distance_km, v.plate_number,
        min(n.estimated_arrival) as first_pickup, count(n.id) as stop_count
    from public.routes r
    join public.vehicles v on v.id = r.vehicle_id
    join public.route_nodes n on n.route_id = r.id and n.superseded_at is null
    where v.assigned_driver_id = $1 and r.status = 'active'
    group by r.id, v.plate_number
"""


async def current_route(conn: asyncpg.Connection, driver_id: UUID) -> DriverRoute | None:
    """The driver's active route whose first stop comes first."""
    route = await conn.fetchrow(
        f"select * from ({_DRIVER_ROUTES}) d order by first_pickup, id limit 1", driver_id
    )
    if route is None:
        return None
    stops = await conn.fetch(_STOPS, route["id"])
    return DriverRoute(
        route_id=route["id"],
        status=route["status"],
        vehicle_plate=route["plate_number"],
        stops=[
            DriverStop(
                route_node_id=s["route_node_id"],
                seq_order=s["seq_order"],
                crew_name=s["crew_name"],
                zone_label=s["zone_label"],
                scheduled_pickup=s["estimated_arrival"],
                lat=round(s["lat"], COORDINATE_DECIMALS),
                lon=round(s["lon"], COORDINATE_DECIMALS),
            )
            for s in stops
        ],
    )


def encode_cursor(first_pickup: datetime, route_id: UUID) -> str:
    raw = json.dumps([first_pickup.isoformat(), str(route_id)])
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    """Raises ValueError for a cursor this API did not make."""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        first_pickup, route_id = json.loads(base64.urlsafe_b64decode(padded))
        return datetime.fromisoformat(first_pickup), UUID(route_id)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("invalid cursor") from error


async def route_page(
    conn: asyncpg.Connection,
    driver_id: UUID,
    after: tuple[datetime, UUID] | None,
    limit: int,
) -> RouteSummaryPage:
    """The driver's active routes in time order, keyset paginated on
    (first pickup, route id): a page never repeats or skips a route, even
    when routes are added between pages."""
    rows = await conn.fetch(
        f"""
        select * from ({_DRIVER_ROUTES}) d
        where $2::timestamptz is null or (first_pickup, id) > ($2, $3)
        order by first_pickup, id
        limit $4
        """,
        driver_id,
        after[0] if after else None,
        after[1] if after else None,
        limit + 1,
    )
    more = len(rows) > limit
    rows = rows[:limit]
    return RouteSummaryPage(
        items=[
            RouteSummary(
                route_id=r["id"],
                status=r["status"],
                vehicle_plate=r["plate_number"],
                first_pickup=r["first_pickup"],
                stop_count=r["stop_count"],
                total_distance_km=float(r["total_distance_km"]),
            )
            for r in rows
        ],
        next_cursor=encode_cursor(rows[-1]["first_pickup"], rows[-1]["id"]) if more else None,
    )


async def next_pickup(
    conn: asyncpg.Connection, crew_member_id: UUID, now: datetime
) -> CrewPickup | None:
    """The crew member's next pickup still to happen: pending or assigned,
    reporting from now on, earliest first; with the time and van of its live
    route node when it has one. crew_member_id is the explicit second check."""
    row = await conn.fetchrow(
        """
        select p.id, p.status, p.report_time,
            n.estimated_arrival, v.plate_number
        from public.pickup_requests p
        left join public.route_nodes n
            on n.pickup_request_id = p.id and n.superseded_at is null
        left join public.routes r on r.id = n.route_id
        left join public.vehicles v on v.id = r.vehicle_id
        where p.crew_member_id = $1
          and p.status in ('pending', 'assigned')
          and p.report_time >= $2
        order by p.report_time, p.id
        limit 1
        """,
        crew_member_id,
        now,
    )
    if row is None:
        return None
    return CrewPickup(
        pickup_request_id=row["id"],
        status=row["status"],
        report_time=row["report_time"],
        scheduled_pickup=row["estimated_arrival"],
        vehicle_plate=row["plate_number"],
    )
