"""Add pickup and Set home without a CSV (#253), and the two reads the
screens need: crew search and a map pin's nearest zone.

Both writes reject what the roster import (app/roster.py) rejects, for the
same reasons, so a pickup is refused the same way whichever path adds it:
- report_time_past: the report time has passed (the import's parse rule);
- outside_pickup_zones: the point is over 10 km from every pickup zone, by
  the import's own PostGIS query (roster._NEAREST_ZONE, ST_DWithin on
  geography);
- duplicate_pickup: the crew member already has a pickup, not cancelled,
  at that report time.
The import's no_pickup_location can't happen here: every stored crew member
has a home (crew_members.home_location is not null).

Everything runs as the dispatcher under RLS. Nothing here starts a re-plan.
"""

import hashlib
from datetime import datetime
from uuid import UUID

import asyncpg

from app.dispatch import _PICKUPS, _pickup, encode_cursor
from app.models.schemas import (
    CrewHome,
    CrewListItem,
    CrewListPage,
    DispatcherPickup,
    LatLon,
    NearestZone,
    PickupRequestCreate,
    RejectReason,
)
from app.reads import COORDINATE_DECIMALS
from app.roster import _NEAREST_ZONE, ZONE_RADIUS_M


class Rejected(Exception):
    """A pickup or home the import would reject, with its reason."""

    def __init__(self, reason: RejectReason, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


class KeyReused(Exception):
    """The Idempotency-Key already added a pickup from a different body."""


# A point from $lat, $lon, as the import makes them.
_POINT = "extensions.st_setsrid(extensions.st_makepoint({lon}, {lat}), 4326)::extensions.geography"


def _rounded(lat: float, lon: float) -> LatLon:
    return LatLon(lat=round(lat, COORDINATE_DECIMALS), lon=round(lon, COORDINATE_DECIMALS))


# Crew in name order. q is matched with strpos, not LIKE, so a % or _ typed
# in the search box is a plain character.
_CREW = """
    select c.id, c.staff_no, c.name, c.role,
        extensions.st_y(c.home_location::extensions.geometry) as lat,
        extensions.st_x(c.home_location::extensions.geometry) as lon,
        z.label as zone_label
    from public.crew_members c
    left join lateral (
        select label from public.pickup_zones
        order by extensions.st_distance(location, c.home_location)
        limit 1
    ) z on true
    where ($1 = '' or strpos(lower(c.name), lower($1)) > 0
           or strpos(lower(coalesce(c.staff_no, '')), lower($1)) > 0)
      and ($2::text is null or (c.name, c.id) > ($2, $3))
    order by c.name, c.id
    limit $4
"""


async def crew_page(
    conn: asyncpg.Connection, q: str, after: tuple[str, UUID] | None, limit: int
) -> CrewListPage:
    rows = await conn.fetch(
        _CREW, q, after[0] if after else None, after[1] if after else None, limit + 1
    )
    more = len(rows) > limit
    rows = rows[:limit]
    return CrewListPage(
        items=[
            CrewListItem(
                id=r["id"],
                staff_no=r["staff_no"],
                name=r["name"],
                crew_role=r["role"],
                home=_rounded(r["lat"], r["lon"]),
                home_zone_label=r["zone_label"],
            )
            for r in rows
        ],
        next_cursor=encode_cursor(rows[-1]["name"], rows[-1]["id"]) if more else None,
    )


async def nearest_zone(conn: asyncpg.Connection, point: LatLon) -> NearestZone:
    """The import's zone check for one point."""
    row = await conn.fetchrow(_NEAREST_ZONE, [point.lat], [point.lon], ZONE_RADIUS_M)
    if row is None:
        raise RuntimeError("no pickup zones: run migration 019")
    return NearestZone(
        zone_label=row["label"], distance_km=row["distance_km"], within_pickup_zones=row["near"]
    )


async def _check_point(conn: asyncpg.Connection, point: LatLon) -> NearestZone:
    zone = await nearest_zone(conn, point)
    if not zone.within_pickup_zones:
        raise Rejected(
            RejectReason.OUTSIDE_PICKUP_ZONES,
            f"over {ZONE_RADIUS_M // 1000} km from every pickup zone "
            f"(nearest: {zone.zone_label}, {zone.distance_km} km)",
        )
    return zone


async def _pickup_by_id(conn: asyncpg.Connection, pickup_id: UUID) -> DispatcherPickup:
    return _pickup(await conn.fetchrow(f"{_PICKUPS} where p.id = $1", pickup_id))


async def _by_key(conn: asyncpg.Connection, key: str, digest: str) -> DispatcherPickup | None:
    stored = await conn.fetchrow(
        "select id, request_hash from public.pickup_requests where idempotency_key = $1", key
    )
    if stored is None:
        return None
    if stored["request_hash"] != digest:
        raise KeyReused(key)
    return await _pickup_by_id(conn, stored["id"])


async def add_pickup(
    conn: asyncpg.Connection, body: PickupRequestCreate, key: str, now: datetime
) -> DispatcherPickup | None:
    """The new pending pickup, or the one this key already added; None for
    an unknown crew member. Raises Rejected or KeyReused."""
    digest = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    if (done := await _by_key(conn, key, digest)) is not None:
        return done
    if not await conn.fetchval(
        "select exists (select 1 from public.crew_members where id = $1)", body.crew_member_id
    ):
        return None
    # The import's order: the time as the row is read, then the zone and the
    # stored duplicate in the database.
    if body.report_time <= now:
        raise Rejected(RejectReason.REPORT_TIME_PAST, "report_time: already past")
    if body.pickup_location is not None:
        await _check_point(conn, body.pickup_location)
    if await conn.fetchval(
        """
        select exists (
            select 1 from public.pickup_requests
            where crew_member_id = $1 and report_time = $2 and status <> 'cancelled'
        )
        """,
        body.crew_member_id,
        body.report_time,
    ):
        raise Rejected(
            RejectReason.DUPLICATE_PICKUP,
            "this crew member already has a pickup at this report time",
        )
    pickup_id = await conn.fetchval(
        f"""
        insert into public.pickup_requests (crew_member_id, pickup_location, report_time,
            request_type, status, idempotency_key, request_hash)
        select c.id, coalesce({_POINT.format(lat="$2::float8", lon="$7::float8")},
                c.home_location),
            $3, $4, 'pending', $5, $6
        from public.crew_members c where c.id = $1
        on conflict (idempotency_key) do nothing
        returning id
        """,
        body.crew_member_id,
        body.pickup_location.lat if body.pickup_location else None,
        body.report_time,
        body.request_type.value,
        key,
        digest,
        body.pickup_location.lon if body.pickup_location else None,
    )
    if pickup_id is None:
        # A request with the same key committed in the meantime.
        return await _by_key(conn, key, digest)
    return await _pickup_by_id(conn, pickup_id)


async def set_home(
    conn: asyncpg.Connection, crew_member_id: UUID, point: LatLon
) -> CrewHome | None:
    """Move the home to the point; None for an unknown crew member. Pickups
    already stored keep their points. Raises Rejected beyond 10 km."""
    if not await conn.fetchval(
        "select exists (select 1 from public.crew_members where id = $1)", crew_member_id
    ):
        return None
    zone = await _check_point(conn, point)
    await conn.execute(
        f"update public.crew_members set home_location = "
        f"{_POINT.format(lat='$2::float8', lon='$3::float8')} where id = $1",
        crew_member_id,
        point.lat,
        point.lon,
    )
    return CrewHome(
        id=crew_member_id,
        home=_rounded(point.lat, point.lon),
        zone_label=zone.zone_label,
        distance_km=zone.distance_km,
    )
