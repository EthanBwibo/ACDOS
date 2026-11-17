"""Roster CSV import (#229): the dispatcher's way to put crew and their
pickups into the system. The CSV format is in docs/roster_import.md.

Two steps:
1. parse() reads the file in Python and checks what needs no database: the
   columns, each field (pickup_location as a lat, lon pair or a Google Maps
   link, #245), the report time being in the future, and the same pickup
   listed twice in the file.
2. run() checks the rest in SQL, as the dispatcher under RLS: each given
   pickup point's nearest zone and its distance (PostGIS on geography, no
   distance maths here), rejecting a point more than 10 km from every zone;
   the crew member having no pickup at that report time already; and a new
   crew member having a location on some row. Then it upserts the crew by
   staff_no and inserts one pending pickup per accepted row, all in the
   caller's one transaction. A row with no location is picked up from the
   crew member's home_location.

A rejected row is skipped and reported with its line and reason; the other
rows still import. A whole-file problem (not CSV, a missing column, over 500
rows) is BadFile, and nothing is imported.

A dry run does all of the same inside a savepoint and rolls it back, so its
counts are exactly what the real import would do. A real import stores its
result under the Idempotency-Key (roster_imports, migration 032): a retry
with the same key and file gets that result back and imports nothing.

Nothing here starts a re-plan. The dispatcher does that with POST
/optimisation-jobs.
"""

import csv
import hashlib
import io
import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import UUID

import asyncpg

from app.models.schemas import (
    PickupRequestType,
    RejectedRow,
    RejectReason,
    RosterImportResult,
    RowLocation,
)

COLUMNS = ("staff_no", "name", "crew_role", "report_time")
OPTIONAL_COLUMNS = ("pickup_location", "request_type")
# The columns pickup_location replaced (#245). A file that still has them is
# refused as a whole: read as "no location" its rows would silently fall back
# to home locations.
REPLACED_COLUMNS = ("pickup_lat", "pickup_lon")
MAX_ROWS = 500
# 500 rows of about 120 bytes each, with room to spare. Enforced on the bytes
# read by app/body_limit.py, before the file is parsed.
MAX_BYTES = 256 * 1024
# A pickup further than this from every one of the 28 zones is outside the
# area the Random Forest was trained on.
ZONE_RADIUS_M = 10_000
MAX_TEXT = 200
# A Google Maps link with its data= part is often 300 to 600 characters.
MAX_LOCATION = 2000


class BadFile(Exception):
    """The file as a whole can't be imported: 422, and nothing is written."""


class KeyReused(Exception):
    """The Idempotency-Key already imported a different file."""


@dataclass(frozen=True)
class RosterRow:
    line: int
    staff_no: str
    name: str
    crew_role: str
    lat: float | None  # both None when the row gives no pickup_location
    lon: float | None
    report_time: datetime
    request_type: PickupRequestType

    @property
    def located(self) -> bool:
        return self.lat is not None


def file_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _text(row: dict, column: str) -> str:
    value = (row.get(column) or "").strip()
    if not value:
        raise ValueError(f"{column}: missing")
    if len(value) > MAX_TEXT:
        raise ValueError(f"{column}: longer than {MAX_TEXT} characters")
    return value


# Pickup points (#245), as Google Maps gives them. Decimal degrees only.
_DEGREES = r"[-+]?\d{1,3}(?:\.\d+)?"
# "-1.292533, 36.787543": what right-clicking a point in Google Maps copies.
_PAIR = re.compile(rf"^\s*({_DEGREES})\s*,\s*({_DEGREES})\s*$")
# In a place link's data= part, the pin itself: !3d<lat>!4d<lon>.
_PIN = re.compile(rf"!3d({_DEGREES})!4d({_DEGREES})")
# In a link's path, the centre of the map view: @<lat>,<lon>,<zoom>z.
_VIEW = re.compile(rf"@({_DEGREES}),({_DEGREES})(?:,|$)")
# Query parameters that carry a point, e.g. ?q=-1.29,36.78 or ?api=1&query=...
_POINT_PARAMS = ("q", "query", "ll", "destination", "center")
_MAPS_HOST = re.compile(r"^(?:maps\.google\.[a-z.]+|(?:www\.)?google\.[a-z.]+)$")
_SHORT_HOSTS = ("maps.app.goo.gl", "goo.gl")


def _in_range(lat: float, lon: float) -> tuple[float, float]:
    if not -90 <= lat <= 90:
        raise ValueError("pickup_location: latitude must be between -90 and 90")
    if not -180 <= lon <= 180:
        raise ValueError("pickup_location: longitude must be between -180 and 180")
    return lat, lon


def _pair(text: str) -> tuple[float, float] | None:
    match = _PAIR.match(text.replace("+", " "))
    return (float(match[1]), float(match[2])) if match else None


def _from_maps_link(raw: str) -> tuple[float, float]:
    url = urlsplit(raw)
    host = (url.hostname or "").lower()
    if host in _SHORT_HOSTS:
        raise ValueError(
            "pickup_location: a short maps.app.goo.gl link has no coordinates in it; "
            "open it and copy the full link from the address bar, or the coordinates"
        )
    if not _MAPS_HOST.match(host) or not (host.startswith("maps.") or url.path.startswith("/maps")):
        raise ValueError("pickup_location: not a Google Maps link")
    path = unquote(url.path)
    # Most precise first: the pin, a point given outright, then the view's centre.
    if pin := _PIN.search(path + unquote(url.query)):
        return float(pin[1]), float(pin[2])
    params = parse_qs(url.query)
    for key in _POINT_PARAMS:
        for value in params.get(key, []):
            if point := _pair(value.removeprefix("loc:")):
                return point
    for part in path.split("/"):
        if point := _pair(part):
            return point  # /maps/place/-1.29,36.78 or /maps/search/-1.29,+36.78
    if view := _VIEW.search(path):
        return float(view[1]), float(view[2])
    raise ValueError(
        "pickup_location: no coordinates in this Google Maps link; "
        "right-click the point in Google Maps and copy its coordinates instead"
    )


def pickup_point(raw: str) -> tuple[float, float] | None:
    """A pickup_location value as (lat, lon), or None when it is blank. It is
    either "lat, lon" as copied from Google Maps, or a Google Maps link with
    the coordinates in it. Anything else raises ValueError with the reason."""
    text = raw.strip()
    if not text:
        return None
    if len(text) > MAX_LOCATION:
        raise ValueError(f"pickup_location: longer than {MAX_LOCATION} characters")
    if text.lower().startswith(("http://", "https://")):
        return _in_range(*_from_maps_link(text))
    if point := _pair(text):
        return _in_range(*point)
    if "°" in text:
        raise ValueError(
            "pickup_location: degrees, minutes and seconds aren't read; "
            "copy the decimal coordinates, e.g. -1.292533, 36.787543"
        )
    raise ValueError(
        "pickup_location: not a lat, lon pair (e.g. -1.292533, 36.787543) or a Google Maps link"
    )


def _report_time(row: dict) -> datetime:
    raw = _text(row, "report_time")
    try:
        value = datetime.fromisoformat(raw)
    except ValueError:
        raise ValueError("report_time: not an ISO 8601 date and time") from None
    if value.tzinfo is None:
        # Without an offset the instant is ambiguous: Nairobi or UTC?
        raise ValueError("report_time: needs a UTC offset, e.g. +03:00")
    return value


def _request_type(row: dict) -> PickupRequestType:
    raw = (row.get("request_type") or "").strip().lower()
    if not raw:
        return PickupRequestType.ROSTERED
    try:
        return PickupRequestType(raw)
    except ValueError:
        raise ValueError("request_type: must be rostered or standby") from None


def _read_row(line: int, row: dict) -> RosterRow:
    if None in row:
        raise ValueError("more fields than columns")
    staff_no = _text(row, "staff_no")
    name = _text(row, "name")
    crew_role = _text(row, "crew_role")
    point = pickup_point(row.get("pickup_location") or "")
    return RosterRow(
        line=line,
        staff_no=staff_no,
        name=name,
        crew_role=crew_role,
        lat=point[0] if point else None,
        lon=point[1] if point else None,
        report_time=_report_time(row),
        request_type=_request_type(row),
    )


def parse(content: bytes, now: datetime) -> tuple[list[RosterRow], list[RejectedRow], int]:
    """The rows that pass the checks needing no database, the rejected ones,
    and the number of data rows in the file."""
    try:
        # utf-8-sig: Excel's "CSV UTF-8" starts the file with a byte order mark.
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise BadFile("the file is not UTF-8 text") from None
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if reader.fieldnames is None:
        raise BadFile("the file is empty")
    reader.fieldnames = [name.strip().lower() for name in reader.fieldnames]
    if any(c in reader.fieldnames for c in REPLACED_COLUMNS):
        raise BadFile(
            "pickup_lat and pickup_lon were replaced by one pickup_location column "
            "(lat, lon or a Google Maps link): see docs/roster_import.md"
        )
    missing = [c for c in COLUMNS if c not in reader.fieldnames]
    if missing:
        raise BadFile(f"missing columns: {', '.join(missing)}")

    rows: list[RosterRow] = []
    rejected: list[RejectedRow] = []
    first_seen: dict[tuple[str, datetime], int] = {}
    count = 0
    for record in reader:
        if all(not (v or "").strip() for v in record.values() if isinstance(v, str)):
            continue  # a line of empty fields, e.g. ",,,,," at the end of a spreadsheet
        count += 1
        if count > MAX_ROWS:
            raise BadFile(f"over {MAX_ROWS} rows: split the roster into smaller files")
        # line_num is the line the row ended on; the header is line 1.
        line = reader.line_num
        staff_no = (record.get("staff_no") or "").strip() or None
        try:
            row = _read_row(line, record)
        except ValueError as error:
            rejected.append(
                RejectedRow(
                    line=line, staff_no=staff_no, reason=RejectReason.INVALID_ROW, detail=str(error)
                )
            )
            continue
        if row.report_time <= now:
            rejected.append(
                RejectedRow(
                    line=line,
                    staff_no=row.staff_no,
                    reason=RejectReason.REPORT_TIME_PAST,
                    detail="report_time: already past",
                )
            )
            continue
        key = (row.staff_no, row.report_time)
        if key in first_seen:
            rejected.append(
                RejectedRow(
                    line=line,
                    staff_no=row.staff_no,
                    reason=RejectReason.DUPLICATE_PICKUP,
                    detail=f"the same pickup is on line {first_seen[key]}",
                )
            )
            continue
        first_seen[key] = line
        rows.append(row)
    return rows, rejected, count


# For each given point ($1 lat, $2 lon, by position from 1): the nearest
# pickup zone, its distance in km to 0.1, and whether it is within the
# radius ($3, metres) of that zone, so of any zone.
_NEAREST_ZONE = """
    select r.i, z.label,
        round((extensions.st_distance(z.location, r.point) / 1000)::numeric, 1)::float8
            as distance_km,
        extensions.st_dwithin(z.location, r.point, $3) as near
    from (
        select u.i,
            extensions.st_setsrid(extensions.st_makepoint(u.lon, u.lat), 4326)
                ::extensions.geography as point
        from unnest($1::float8[], $2::float8[]) with ordinality as u(lat, lon, i)
    ) r
    cross join lateral (
        select label, location from public.pickup_zones
        order by extensions.st_distance(location, r.point)
        limit 1
    ) z
"""

# Which rows ($1 staff_no, $2 report_time) a known crew member already has a
# pickup for. A cancelled pickup doesn't count: the crew member can be
# rostered at that time again.
_ALREADY_STORED = """
    select r.i
    from unnest($1::text[], $2::timestamptz[]) with ordinality as r(staff_no, report_time, i)
    where exists (
        select 1
        from public.pickup_requests p
        join public.crew_members c on c.id = p.crew_member_id
        where c.staff_no = r.staff_no
          and p.report_time = r.report_time
          and p.status <> 'cancelled'
    )
"""


async def _check_in_db(
    conn: asyncpg.Connection, rows: list[RosterRow]
) -> tuple[list[RosterRow], list[RejectedRow], list[RowLocation]]:
    located = [row for row in rows if row.located]
    zones = {
        located[r["i"] - 1].line: r
        for r in await conn.fetch(
            _NEAREST_ZONE, [r.lat for r in located], [r.lon for r in located], ZONE_RADIUS_M
        )
    }
    locations = [
        RowLocation(
            line=row.line,
            staff_no=row.staff_no,
            zone_label=zones[row.line]["label"],
            distance_km=zones[row.line]["distance_km"],
        )
        for row in located
        if row.line in zones
    ]
    near = {line for line, z in zones.items() if z["near"]}
    stored = {
        r["i"]
        for r in await conn.fetch(
            _ALREADY_STORED, [r.staff_no for r in rows], [r.report_time for r in rows]
        )
    }
    known = {
        r["staff_no"]
        for r in await conn.fetch(
            "select staff_no from public.crew_members where staff_no = any($1::text[])",
            list({r.staff_no for r in rows}),
        )
    }
    # A new crew member's home is their first accepted point in the file.
    # A stored duplicate can't be one: a new crew member has no pickups yet.
    homed = known | {r.staff_no for r in located if r.line in near}
    accepted, rejected = [], []
    for i, row in enumerate(rows, start=1):
        if row.located and row.line not in near:
            rejected.append(
                RejectedRow(
                    line=row.line,
                    staff_no=row.staff_no,
                    reason=RejectReason.OUTSIDE_PICKUP_ZONES,
                    detail=f"over {ZONE_RADIUS_M // 1000} km from every pickup zone",
                )
            )
        elif i in stored:
            rejected.append(
                RejectedRow(
                    line=row.line,
                    staff_no=row.staff_no,
                    reason=RejectReason.DUPLICATE_PICKUP,
                    detail="this crew member already has a pickup at this report time",
                )
            )
        elif row.staff_no not in homed:
            rejected.append(
                RejectedRow(
                    line=row.line,
                    staff_no=row.staff_no,
                    reason=RejectReason.NO_PICKUP_LOCATION,
                    detail="new crew member needs a pickup location",
                )
            )
        else:
            accepted.append(row)
    return accepted, rejected, locations


async def _write(conn: asyncpg.Connection, rows: list[RosterRow]) -> tuple[int, int, int]:
    """Upsert the crew by staff_no, then one pending pickup per row. Returns
    (crew created, crew updated, pickups created)."""
    # One crew record per staff number: name and role from its first row in
    # the file, home from its first row with a location.
    crew: dict[str, RosterRow] = {}
    home: dict[str, RosterRow] = {}
    for row in rows:
        crew.setdefault(row.staff_no, row)
        if row.located:
            home.setdefault(row.staff_no, row)
    known = {
        r["staff_no"]: r["id"]
        for r in await conn.fetch(
            "select staff_no, id from public.crew_members where staff_no = any($1::text[])",
            list(crew),
        )
    }
    # Known crew: refresh name and role. Their home_location stays: a roster
    # pickup point can be a one-off (a hotel), not where they live.
    await conn.execute(
        """
        update public.crew_members c
        set name = u.name, role = u.role
        from unnest($1::text[], $2::text[], $3::text[]) as u(staff_no, name, role)
        where c.staff_no = u.staff_no
        """,
        [s for s in crew if s in known],
        [crew[s].name for s in crew if s in known],
        [crew[s].crew_role for s in crew if s in known],
    )
    # New crew: their first pickup point is their home location, which the
    # schema requires. _check_in_db rejected the rows of new crew without one.
    new = [s for s in crew if s not in known]
    for r in await conn.fetch(
        """
        insert into public.crew_members (staff_no, name, role, home_location)
        select u.staff_no, u.name, u.role,
            extensions.st_setsrid(extensions.st_makepoint(u.lon, u.lat), 4326)::extensions.geography
        from unnest($1::text[], $2::text[], $3::text[], $4::float8[], $5::float8[])
            as u(staff_no, name, role, lat, lon)
        returning staff_no, id
        """,
        new,
        [crew[s].name for s in new],
        [crew[s].crew_role for s in new],
        [home[s].lat for s in new],
        [home[s].lon for s in new],
    ):
        known[r["staff_no"]] = r["id"]
    # A row with no location is picked up from home: st_makepoint of nulls is
    # null, so coalesce falls back to home_location.
    await conn.execute(
        """
        insert into public.pickup_requests
            (crew_member_id, pickup_location, report_time, request_type, status)
        select u.crew_member_id,
            coalesce(
                extensions.st_setsrid(extensions.st_makepoint(u.lon, u.lat), 4326)
                    ::extensions.geography,
                c.home_location
            ),
            u.report_time, u.request_type, 'pending'
        from unnest($1::uuid[], $2::float8[], $3::float8[], $4::timestamptz[], $5::text[])
            as u(crew_member_id, lat, lon, report_time, request_type)
        join public.crew_members c on c.id = u.crew_member_id
        """,
        [known[r.staff_no] for r in rows],
        [r.lat for r in rows],
        [r.lon for r in rows],
        [r.report_time for r in rows],
        [r.request_type.value for r in rows],
    )
    return len(new), len(crew) - len(new), len(rows)


class _Undo(Exception):
    """Rolls the savepoint back: a dry run, or a key another import took."""

    def __init__(self, result: RosterImportResult | None) -> None:
        self.result = result


async def _stored(conn: asyncpg.Connection, key: str, digest: str) -> RosterImportResult | None:
    row = await conn.fetchrow(
        "select file_hash, result::text from public.roster_imports where idempotency_key = $1",
        key,
    )
    if row is None:
        return None
    if row["file_hash"] != digest:
        raise KeyReused(key)
    return RosterImportResult.model_validate_json(row["result"])


async def run(
    conn: asyncpg.Connection,
    content: bytes,
    now: datetime,
    *,
    dry_run: bool,
    idempotency_key: str | None,
    dispatcher_id: UUID,
) -> RosterImportResult:
    """Validate the file and import it (or, with dry_run, say what importing
    would do). conn is the caller's transaction (app/reads.py)."""
    digest = file_hash(content)
    if not dry_run:
        assert idempotency_key is not None
        earlier = await _stored(conn, idempotency_key, digest)
        if earlier is not None:
            return earlier
    rows, rejected, count = parse(content, now)
    try:
        async with conn.transaction():  # a savepoint inside the caller's transaction
            accepted, also_rejected, locations = (
                await _check_in_db(conn, rows) if rows else ([], [], [])
            )
            created, updated, pickups = await _write(conn, accepted) if accepted else (0, 0, 0)
            all_rejected = sorted(rejected + also_rejected, key=lambda r: r.line)
            result = RosterImportResult(
                dry_run=dry_run,
                rows=count,
                crew_created=created,
                crew_updated=updated,
                pickups_created=pickups,
                rows_rejected=len(all_rejected),
                rejected=all_rejected,
                locations=locations,
            )
            if dry_run:
                raise _Undo(result)
            # Claim the key last: an import running at the same time with the
            # same key waits here until that one commits, then finds it taken.
            claimed = await conn.fetchval(
                """
                insert into public.roster_imports
                    (idempotency_key, file_hash, imported_by, result)
                values ($1, $2, $3, $4::jsonb)
                on conflict (idempotency_key) do nothing
                returning id
                """,
                idempotency_key,
                digest,
                dispatcher_id,
                result.model_dump_json(),
            )
            if claimed is None:
                raise _Undo(None)
            return result
    except _Undo as undo:
        if undo.result is not None:
            return undo.result
    # Another import took the key while this one ran: its result, not a second copy.
    earlier = await _stored(conn, idempotency_key, digest)
    assert earlier is not None
    return earlier
