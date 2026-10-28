"""Where optimisation jobs and their plans are kept (#51).

JobStore is what the API and the runner need. PostgresJobStore is the real
one; tests use an in-memory one (tests/fake_job_store.py) for the API and
run this one against Postgres (tests/test_job_store_postgres.py).

The backend connects as the postgres role, which bypasses RLS: the API
checks requests itself. Every name is schema-qualified, PostGIS included
(extensions, migration 000), so nothing depends on the connection's
search_path.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

import asyncpg

from app.jobs.worker import SolveOutcome
from app.models.schemas import (
    LatePickup,
    OptimisationJobResult,
    OptimizationJobStatus,
    OptimizationTriggerType,
    PlannedNode,
    PlannedRoute,
)
from app.solver.problem import JKIA, Point


@dataclass(frozen=True)
class StoredPickup:
    id: UUID
    location: Point
    report_time: datetime
    status: str


@dataclass(frozen=True)
class StoredVehicle:
    id: UUID
    capacity: int


@dataclass(frozen=True)
class KeyedJob:
    id: UUID
    request_hash: str
    # True only for the request whose insert made the job, so a job is
    # handed to the runner once however many requests race on its key.
    created: bool = False


class DepartedRouteError(Exception):
    """A requested pickup is on a route that has already left: re-planning
    it is #113's job, not this API's."""

    def __init__(self, pickup_ids: list[UUID]) -> None:
        super().__init__(f"pickups on departed routes: {sorted(map(str, pickup_ids))}")
        self.pickup_ids = pickup_ids


class JobStore(Protocol):
    async def job_for_key(self, idempotency_key: str) -> KeyedJob | None: ...

    async def pickups(self, ids: list[UUID]) -> dict[UUID, StoredPickup]: ...

    async def vehicles(self, ids: list[UUID]) -> dict[UUID, StoredVehicle]: ...

    async def on_departed_routes(self, pickup_ids: list[UUID], now: datetime) -> list[UUID]: ...

    async def create_job(
        self, idempotency_key: str, request_hash: str, trigger_type: OptimizationTriggerType
    ) -> KeyedJob: ...

    async def mark_running(self, job_id: UUID) -> None: ...

    async def complete(self, job_id: UUID, outcome: SolveOutcome, now: datetime) -> None: ...

    async def fail(self, job_id: UUID, error: str) -> None: ...

    async def fail_unfinished(self) -> int: ...

    async def result(self, job_id: UUID) -> OptimisationJobResult | None: ...


# A route has departed once a pickup on it is recorded (confirmed or an
# exception), once the time for its first stop has passed, or once it is
# completed. Before that it can still be replaced. $2 is now.
_DEPARTED_ROUTE = """
    r.status = 'completed'
    or exists (
        select 1 from public.route_nodes rn
        join public.pickup_events e on e.route_node_id = rn.id
        where rn.route_id = r.id
    )
    or (
        select min(rn.estimated_arrival) from public.route_nodes rn
        where rn.route_id = r.id and rn.superseded_at is null
    ) <= $2
"""

# Live nodes of the requested pickups ($1) on routes still in use.
_LIVE_NODES = """
    from public.route_nodes n
    join public.routes r on r.id = n.route_id
    where n.pickup_request_id = any($1::uuid[])
      and n.superseded_at is null
      and r.status in ('active', 'completed')
"""

# Straight-line length of a route ($1): depot ($2, $3) to each stop in turn,
# then JKIA ($4, $5), by PostGIS on geography (CLAUDE.md: no distance math
# in the API layer).
_ROUTE_LENGTH_KM = """
    with stops as (
        select 0 as seq,
            extensions.st_setsrid(extensions.st_makepoint($3, $2), 4326)::extensions.geography
                as place
        union all
        select n.seq_order, p.pickup_location
        from public.route_nodes n
        join public.pickup_requests p on p.id = n.pickup_request_id
        where n.route_id = $1
        union all
        select 2147483647,
            extensions.st_setsrid(extensions.st_makepoint($5, $4), 4326)::extensions.geography
    ),
    legs as (
        select extensions.st_distance(place, lag(place) over (order by seq)) as metres
        from stops
    )
    update public.routes
    set total_distance_km = (select sum(metres) / 1000 from legs)
    where id = $1
"""


class PostgresJobStore:
    def __init__(self, pool: asyncpg.Pool, depot: Point) -> None:
        self._pool = pool
        self._depot = depot

    async def job_for_key(self, idempotency_key: str) -> KeyedJob | None:
        row = await self._pool.fetchrow(
            "select id, request_hash from public.optimization_jobs where idempotency_key = $1",
            idempotency_key,
        )
        return KeyedJob(row["id"], row["request_hash"]) if row else None

    async def pickups(self, ids: list[UUID]) -> dict[UUID, StoredPickup]:
        rows = await self._pool.fetch(
            """
            select id, status, report_time,
                extensions.st_y(pickup_location::extensions.geometry) as lat,
                extensions.st_x(pickup_location::extensions.geometry) as lon
            from public.pickup_requests
            where id = any($1::uuid[])
            """,
            ids,
        )
        return {
            r["id"]: StoredPickup(r["id"], Point(r["lat"], r["lon"]), r["report_time"], r["status"])
            for r in rows
        }

    async def vehicles(self, ids: list[UUID]) -> dict[UUID, StoredVehicle]:
        rows = await self._pool.fetch(
            "select id, capacity from public.vehicles where id = any($1::uuid[])", ids
        )
        return {r["id"]: StoredVehicle(r["id"], r["capacity"]) for r in rows}

    async def on_departed_routes(self, pickup_ids: list[UUID], now: datetime) -> list[UUID]:
        return await _on_departed_routes(self._pool, pickup_ids, now)

    async def create_job(
        self, idempotency_key: str, request_hash: str, trigger_type: OptimizationTriggerType
    ) -> KeyedJob:
        row = await self._pool.fetchrow(
            """
            insert into public.optimization_jobs
                (trigger_type, status, idempotency_key, request_hash)
            values ($1, 'queued', $2, $3)
            on conflict (idempotency_key) do nothing
            returning id, request_hash
            """,
            trigger_type.value,
            idempotency_key,
            request_hash,
        )
        if row is None:
            # A request with the same key got in between the lookup and here.
            existing = await self.job_for_key(idempotency_key)
            assert existing is not None
            return existing
        return KeyedJob(row["id"], row["request_hash"], created=True)

    async def mark_running(self, job_id: UUID) -> None:
        await self._pool.execute(
            "update public.optimization_jobs set status = 'running' where id = $1", job_id
        )

    async def complete(self, job_id: UUID, outcome: SolveOutcome, now: datetime) -> None:
        """Write the plan and complete the job in one transaction, so a job is
        never completed without its routes, and a failure leaves nothing."""
        routed = [UUID(s.pickup_id) for route in outcome.routes for s in route.stops]
        requested = routed + [UUID(i) for i in outcome.unassigned]
        async with self._pool.acquire() as conn, conn.transaction():
            # The API checked this when the job was accepted; a route may
            # have left while the job queued or ran.
            departed = await _on_departed_routes(conn, requested, now)
            if departed:
                raise DepartedRouteError(departed)

            # Replace the requested pickups' current plan: their nodes are
            # superseded, and so are the routes those nodes were on.
            old_routes = await conn.fetch(
                """
                update public.route_nodes n
                set superseded_at = $2
                from public.routes r
                where r.id = n.route_id
                  and n.pickup_request_id = any($1::uuid[])
                  and n.superseded_at is null
                  and r.status = 'active'
                returning n.route_id
                """,
                requested,
                now,
            )
            await conn.execute(
                "update public.routes set status = 'superseded' where id = any($1::uuid[])",
                list({r["route_id"] for r in old_routes}),
            )

            for route in outcome.routes:
                route_id = await conn.fetchval(
                    """
                    insert into public.routes (vehicle_id, optimization_job_id, total_distance_km)
                    values ($1, $2, 0)
                    returning id
                    """,
                    UUID(route.vehicle_id),
                    job_id,
                )
                await conn.executemany(
                    """
                    insert into public.route_nodes
                        (route_id, pickup_request_id, seq_order, estimated_arrival)
                    values ($1, $2, $3, $4)
                    """,
                    [
                        (route_id, UUID(s.pickup_id), seq, s.arrival)
                        for seq, s in enumerate(route.stops, start=1)
                    ],
                )
                await conn.execute(
                    _ROUTE_LENGTH_KM,
                    route_id,
                    self._depot.lat,
                    self._depot.lon,
                    JKIA.lat,
                    JKIA.lon,
                )

            await conn.execute(
                "update public.pickup_requests set status = 'assigned' where id = any($1::uuid[])",
                routed,
            )
            # An unassigned pickup that was assigned before has just lost its
            # node: it is waiting for a plan again.
            await conn.execute(
                "update public.pickup_requests set status = 'pending' where id = any($1::uuid[])",
                [UUID(i) for i in outcome.unassigned],
            )
            await conn.executemany(
                """
                insert into public.optimization_job_pickups
                    (optimization_job_id, pickup_request_id, outcome, late_sec)
                values ($1, $2, $3, $4)
                """,
                [
                    (job_id, UUID(i), "late" if late else "on_time", late)
                    for i, late in outcome.late_sec.items()
                ]
                + [(job_id, UUID(i), "unassigned", None) for i in outcome.unassigned],
            )
            await conn.execute(
                """
                update public.optimization_jobs
                set status = 'completed', finished_at = $2
                where id = $1
                """,
                job_id,
                now,
            )

    async def fail(self, job_id: UUID, error: str) -> None:
        await self._pool.execute(
            """
            update public.optimization_jobs
            set status = 'failed', error = $2, finished_at = now()
            where id = $1
            """,
            job_id,
            error,
        )

    async def fail_unfinished(self) -> int:
        """Fail every job left queued or running. Run at startup only, with
        one uvicorn process: its solver processes died with the last run, so
        nothing is working on those jobs any more."""
        status = await self._pool.execute(
            """
            update public.optimization_jobs
            set status = 'failed', error = 'backend restarted before the job finished',
                finished_at = now()
            where status in ('queued', 'running')
            """
        )
        return int(status.split()[-1])  # "UPDATE <count>"

    async def result(self, job_id: UUID) -> OptimisationJobResult | None:
        job = await self._pool.fetchrow(
            "select id, status, error from public.optimization_jobs where id = $1", job_id
        )
        if job is None:
            return None
        result = OptimisationJobResult(
            id=job["id"], status=OptimizationJobStatus(job["status"]), error=job["error"]
        )
        if result.status != OptimizationJobStatus.COMPLETED:
            return result
        # The job's own routes, superseded or not: this is what it planned.
        nodes = await self._pool.fetch(
            """
            select r.id as route_id, r.vehicle_id, r.total_distance_km,
                n.pickup_request_id, n.seq_order, n.estimated_arrival
            from public.routes r
            join public.route_nodes n on n.route_id = r.id
            where r.optimization_job_id = $1
            order by r.created_at, r.id, n.seq_order
            """,
            job_id,
        )
        routes: dict[UUID, PlannedRoute] = {}
        for n in nodes:
            route = routes.setdefault(
                n["route_id"],
                PlannedRoute(
                    vehicle_id=n["vehicle_id"],
                    total_distance_km=float(n["total_distance_km"]),
                    nodes=[],
                ),
            )
            route.nodes.append(
                PlannedNode(
                    pickup_request_id=n["pickup_request_id"],
                    seq_order=n["seq_order"],
                    estimated_arrival=n["estimated_arrival"],
                )
            )
        result.routes = list(routes.values())
        outcomes = await self._pool.fetch(
            """
            select pickup_request_id, outcome, late_sec
            from public.optimization_job_pickups
            where optimization_job_id = $1 and outcome <> 'on_time'
            order by pickup_request_id
            """,
            job_id,
        )
        result.late = [
            LatePickup(pickup_request_id=o["pickup_request_id"], late_sec=o["late_sec"])
            for o in outcomes
            if o["outcome"] == "late"
        ]
        result.unassigned = [
            o["pickup_request_id"] for o in outcomes if o["outcome"] == "unassigned"
        ]
        return result


async def _on_departed_routes(
    conn: asyncpg.Pool | asyncpg.Connection, pickup_ids: list[UUID], now: datetime
) -> list[UUID]:
    rows = await conn.fetch(
        f"select n.pickup_request_id {_LIVE_NODES} and ({_DEPARTED_ROUTE}) "
        "order by n.pickup_request_id",
        pickup_ids,
        now,
    )
    return [r["pickup_request_id"] for r in rows]


async def connect(database_url: str) -> asyncpg.Pool:
    # No prepared statement cache: Supabase's transaction pooler (port 6543)
    # hands each statement to any server connection, where a statement
    # prepared on another one does not exist. Harmless on the session pooler.
    return await asyncpg.create_pool(database_url, statement_cache_size=0, min_size=1, max_size=5)
