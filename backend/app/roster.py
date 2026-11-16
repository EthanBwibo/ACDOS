"""Roster CSV import (#229): the dispatcher's way to put crew and their
pickups into the system. The CSV format is in docs/roster_import.md.

Two steps:
1. parse() reads the file in Python and checks what needs no database: the
   columns, each field, the report time being in the future, and the same
   pickup listed twice in the file.
2. run() checks the rest in SQL, as the dispatcher under RLS: the pickup is
   within 10 km of a pickup zone (PostGIS ST_DWithin on geography, no
   distance maths here), and the crew member has no pickup at that report
   time already. Then it upserts the crew by staff_no and inserts one pending
   pickup per accepted row, all in the caller's one transaction.

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
import math
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import asyncpg

from app.models.schemas import (
    PickupRequestType,
    RejectedRow,
    RejectReason,
    RosterImportResult,
)

COLUMNS = ("staff_no", "name", "crew_role", "pickup_lat", "pickup_lon", "report_time")
OPTIONAL_COLUMNS = ("request_type",)
MAX_ROWS = 500
# 500 rows of about 120 bytes each, with room to spare. Enforced on the bytes
# read by app/body_limit.py, before the file is parsed.
MAX_BYTES = 256 * 1024
# A pickup further than this from every one of the 28 zones is outside the
# area the Random Forest was trained on.
ZONE_RADIUS_M = 10_000
MAX_TEXT = 200


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
    lat: float
    lon: float
    report_time: datetime
    request_type: PickupRequestType


def file_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _text(row: dict, column: str) -> str:
    value = (row.get(column) or "").strip()
    if not value:
        raise ValueError(f"{column}: missing")
    if len(value) > MAX_TEXT:
        raise ValueError(f"{column}: longer than {MAX_TEXT} characters")
    return value


def _number(row: dict, column: str, limit: float) -> float:
    raw = _text(row, column)
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"{column}: not a number") from None
    if not math.isfinite(value) or not -limit <= value <= limit:
        raise ValueError(f"{column}: must be between -{limit:g} and {limit:g}")
    return value


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
    return RosterRow(
        line=line,
        staff_no=_text(row, "staff_no"),
        name=_text(row, "name"),
        crew_role=_text(row, "crew_role"),
        lat=_number(row, "pickup_lat", 90),
        lon=_number(row, "pickup_lon", 180),
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


# Which rows ($1 lat, $2 lon, by position from 1) are within the radius ($3,
# metres) of at least one pickup zone.
_NEAR_A_ZONE = """
    select r.i
    from unnest($1::float8[], $2::float8[]) with ordinality as r(lat, lon, i)
    where exists (
        select 1 from public.pickup_zones z
        where extensions.st_dwithin(
            z.location,
            extensions.st_setsrid(extensions.st_makepoint(r.lon, r.lat), 4326)
                ::extensions.geography,
            $3
        )
    )
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
) -> tuple[list[RosterRow], list[RejectedRow]]:
    near = {
        r["i"]
        for r in await conn.fetch(
            _NEAR_A_ZONE, [r.lat for r in rows], [r.lon for r in rows], ZONE_RADIUS_M
        )
    }
    stored = {
        r["i"]
        for r in await conn.fetch(
            _ALREADY_STORED, [r.staff_no for r in rows], [r.report_time for r in rows]
        )
    }
    accepted, rejected = [], []
    for i, row in enumerate(rows, start=1):
        if i not in near:
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
        else:
            accepted.append(row)
    return accepted, rejected


async def _write(conn: asyncpg.Connection, rows: list[RosterRow]) -> tuple[int, int, int]:
    """Upsert the crew by staff_no, then one pending pickup per row. Returns
    (crew created, crew updated, pickups created)."""
    # One crew record per staff number, from its first row in the file.
    crew: dict[str, RosterRow] = {}
    for row in rows:
        crew.setdefault(row.staff_no, row)
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
    # schema requires.
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
        [crew[s].lat for s in new],
        [crew[s].lon for s in new],
    ):
        known[r["staff_no"]] = r["id"]
    await conn.execute(
        """
        insert into public.pickup_requests
            (crew_member_id, pickup_location, report_time, request_type, status)
        select u.crew_member_id,
            extensions.st_setsrid(extensions.st_makepoint(u.lon, u.lat), 4326)
                ::extensions.geography,
            u.report_time, u.request_type, 'pending'
        from unnest($1::uuid[], $2::float8[], $3::float8[], $4::timestamptz[], $5::text[])
            as u(crew_member_id, lat, lon, report_time, request_type)
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
            accepted, also_rejected = await _check_in_db(conn, rows) if rows else ([], [])
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
