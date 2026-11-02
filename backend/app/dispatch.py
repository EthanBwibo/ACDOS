"""Reads and the two updates for the dispatcher's dashboard (#136).

Every function takes a connection already running as the caller
(reads.as_caller), so RLS applies; the router checks the caller is a
dispatcher first. Every name is schema-qualified, PostGIS included.

Lists are keyset paginated on (sort key, id), so a page never repeats or
skips a row when rows are added between pages. A day is a calendar day in
Nairobi (EAT, UTC+3, no daylight saving).
"""

import base64
import json
from datetime import date, datetime, time, timedelta
from uuid import UUID

import asyncpg

from app.jobs.store import ON_THE_ROAD
from app.jobs.worker import EAT
from app.models.schemas import (
    DispatcherPickup,
    DispatcherPickupPage,
    DispatcherRoute,
    DispatcherRoutePage,
    DispatcherVehicle,
    DispatcherVehiclePage,
    PickupRequestStatus,
    PlannedNode,
    VehicleStatus,
)


def day_bounds(day: date) -> tuple[datetime, datetime]:
    """[start, end) of a Nairobi calendar day, as aware datetimes."""
    start = datetime.combine(day, time(), EAT)
    return start, start + timedelta(days=1)


def encode_cursor(key: str, row_id: UUID) -> str:
    raw = json.dumps([key, str(row_id)])
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[str, UUID]:
    """Raises ValueError for a cursor this API did not make."""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        key, row_id = json.loads(base64.urlsafe_b64decode(padded))
        if not isinstance(key, str):
            raise ValueError("invalid cursor")
        return key, UUID(row_id)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("invalid cursor") from error


def time_key(cursor: str | None) -> tuple[datetime, UUID] | None:
    """A cursor whose key is a timestamp. Raises ValueError if it is not."""
    if cursor is None:
        return None
    key, row_id = decode_cursor(cursor)
    return datetime.fromisoformat(key), row_id


# One pickup with what the dashboard lists. The zone is the nearest of
# pickup_zones by PostGIS, as on the driver's route (reads._STOPS).
_PICKUPS = """
    select p.id, c.name as crew_name, z.label as zone_label, p.report_time, p.status
    from public.pickup_requests p
    join public.crew_members c on c.id = p.crew_member_id
    left join lateral (
        select label from public.pickup_zones
        order by extensions.st_distance(location, p.pickup_location)
        limit 1
    ) z on true
"""


def _pickup(row: asyncpg.Record) -> DispatcherPickup:
    return DispatcherPickup(
        id=row["id"],
        crew_name=row["crew_name"],
        zone_label=row["zone_label"],
        report_time=row["report_time"],
        status=row["status"],
    )


async def pickup_page(
    conn: asyncpg.Connection, day: date, after: tuple[datetime, UUID] | None, limit: int
) -> DispatcherPickupPage:
    """The pickups reporting on day, in report-time order."""
    start, end = day_bounds(day)
    rows = await conn.fetch(
        f"""
        select * from ({_PICKUPS}
            where p.report_time >= $1 and p.report_time < $2) d
        where $3::timestamptz is null or (report_time, id) > ($3, $4)
        order by report_time, id
        limit $5
        """,
        start,
        end,
        after[0] if after else None,
        after[1] if after else None,
        limit + 1,
    )
    more = len(rows) > limit
    rows = rows[:limit]
    return DispatcherPickupPage(
        items=[_pickup(r) for r in rows],
        next_cursor=(
            encode_cursor(rows[-1]["report_time"].isoformat(), rows[-1]["id"]) if more else None
        ),
    )


async def update_report_time(
    conn: asyncpg.Connection, pickup_id: UUID, report_time: datetime
) -> DispatcherPickup | str | None:
    """Set a pickup's report time. None if there is no such pickup; its
    status (str) if it is past assigned, which a new report time no longer
    changes. Only the one column: it starts no job."""
    status = await conn.fetchval(
        "select status from public.pickup_requests where id = $1 for update", pickup_id
    )
    if status is None:
        return None
    if status not in (PickupRequestStatus.PENDING, PickupRequestStatus.ASSIGNED):
        return status
    await conn.execute(
        "update public.pickup_requests set report_time = $2 where id = $1", pickup_id, report_time
    )
    return _pickup(await conn.fetchrow(f"{_PICKUPS} where p.id = $1", pickup_id))


async def _vehicles(
    conn: asyncpg.Connection, rows: list[asyncpg.Record], now: datetime, grace: timedelta
) -> list[DispatcherVehicle]:
    away = {
        r["vehicle_id"] for r in await conn.fetch(ON_THE_ROAD, [r["id"] for r in rows], now, grace)
    }
    return [
        DispatcherVehicle(
            id=r["id"],
            plate_number=r["plate_number"],
            capacity=r["capacity"],
            status=r["status"],
            on_the_road=r["id"] in away,
        )
        for r in rows
    ]


async def vehicle_page(
    conn: asyncpg.Connection,
    after: tuple[str, UUID] | None,
    limit: int,
    now: datetime,
    grace: timedelta,
) -> DispatcherVehiclePage:
    """Every vehicle, in plate order."""
    rows = await conn.fetch(
        """
        select id, plate_number, capacity, status from public.vehicles
        where $1::text is null or (plate_number, id) > ($1, $2)
        order by plate_number, id
        limit $3
        """,
        after[0] if after else None,
        after[1] if after else None,
        limit + 1,
    )
    more = len(rows) > limit
    rows = rows[:limit]
    return DispatcherVehiclePage(
        items=await _vehicles(conn, rows, now, grace),
        next_cursor=encode_cursor(rows[-1]["plate_number"], rows[-1]["id"]) if more else None,
    )


async def update_vehicle_status(
    conn: asyncpg.Connection,
    vehicle_id: UUID,
    status: VehicleStatus,
    now: datetime,
    grace: timedelta,
) -> DispatcherVehicle | None:
    """Set a vehicle's status; None if there is no such vehicle. Routes are
    left as they are: a broken-down van's route moves only in a
    vehicle_breakdown re-plan the dispatcher starts (#113)."""
    row = await conn.fetchrow(
        "update public.vehicles set status = $2 where id = $1 "
        "returning id, plate_number, capacity, status",
        vehicle_id,
        status.value,
    )
    if row is None:
        return None
    [vehicle] = await _vehicles(conn, [row], now, grace)
    return vehicle


async def route_page(
    conn: asyncpg.Connection, day: date, after: tuple[datetime, UUID] | None, limit: int
) -> DispatcherRoutePage:
    """The active routes leaving the depot on day, in departure order, each
    with its live stops."""
    start, end = day_bounds(day)
    routes = await conn.fetch(
        """
        select r.id, r.vehicle_id, v.plate_number, r.total_distance_km,
            r.planned_departure, r.planned_arrival
        from public.routes r
        join public.vehicles v on v.id = r.vehicle_id
        where r.status = 'active'
          and r.planned_departure >= $1 and r.planned_departure < $2
          and ($3::timestamptz is null or (r.planned_departure, r.id) > ($3, $4))
        order by r.planned_departure, r.id
        limit $5
        """,
        start,
        end,
        after[0] if after else None,
        after[1] if after else None,
        limit + 1,
    )
    more = len(routes) > limit
    routes = routes[:limit]
    nodes = await conn.fetch(
        """
        select route_id, pickup_request_id, seq_order, estimated_arrival
        from public.route_nodes
        where route_id = any($1::uuid[]) and superseded_at is null
        order by route_id, seq_order
        """,
        [r["id"] for r in routes],
    )
    stops: dict[UUID, list[PlannedNode]] = {}
    for n in nodes:
        stops.setdefault(n["route_id"], []).append(
            PlannedNode(
                pickup_request_id=n["pickup_request_id"],
                seq_order=n["seq_order"],
                estimated_arrival=n["estimated_arrival"],
            )
        )
    return DispatcherRoutePage(
        items=[
            DispatcherRoute(
                route_id=r["id"],
                vehicle_id=r["vehicle_id"],
                vehicle_plate=r["plate_number"],
                total_distance_km=float(r["total_distance_km"]),
                planned_departure=r["planned_departure"],
                planned_arrival=r["planned_arrival"],
                nodes=stops.get(r["id"], []),
            )
            for r in routes
        ],
        next_cursor=(
            encode_cursor(routes[-1]["planned_departure"].isoformat(), routes[-1]["id"])
            if more
            else None
        ),
    )
