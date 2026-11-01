"""Where optimisation jobs and their plans are kept (#51).

JobStore is what the API and the runner need. PostgresJobStore is the real
one; tests use an in-memory one (tests/fake_job_store.py) for the API and
run this one against Postgres (tests/test_optimisation_jobs_postgres.py).

The backend connects as the postgres role, which bypasses RLS: the API
checks requests itself. Every name is schema-qualified, PostGIS included
(extensions, migration 000), so nothing depends on the connection's
search_path.

Re-planning (#113): a job replaces whole routes that have not departed:
the routes of its pickups, and the routes of its vans, so a van never has
two active routes. A departed route stays as it is, and its van stays out
of new plans until it is due back at JKIA. The one exception is a van that broke down: in a
vehicle_breakdown re-plan, its route's pickups not yet collected may go to
other vans.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
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
    status: str = "available"


@dataclass(frozen=True)
class KeyedJob:
    id: UUID
    request_hash: str
    # True only for the request whose insert made the job, so a job is
    # handed to the runner once however many requests race on its key.
    created: bool = False


@dataclass(frozen=True)
class RouteConflicts:
    """Why a set of pickups and vans cannot replace the plan as it is now.

    The API asks before it accepts a job; the store asks again when the job
    commits, since the plan may have changed while it queued or ran.
    """

    # Pickups on a route that has departed (_DEPARTED_ROUTE), which a re-plan
    # never touches; except, in a vehicle_breakdown re-plan, the route of a
    # broken-down van (_FIXED_ROUTE).
    departed: list[UUID]
    # Plannable pickups NOT in the set on a route the job replaces
    # (_REPLACED_ROUTES): a route of one of its pickups, or a requested van's
    # route that has not departed. The API adds them to the job, so a re-plan
    # takes whole routes; at commit, one here means a pickup joined such a
    # route meanwhile, or a requested van was given a route meanwhile.
    left_behind: list[UUID] = ()
    # Pickups in the set past assigned (picked up, missed, cancelled). The
    # API refuses these itself; at commit, one here was collected while the
    # job ran, e.g. by the van it was re-planned away from (migration 025).
    not_plannable: list[UUID] = ()
    # Vans on the road (_ON_THE_ROAD): away from the depot, crew on board.
    on_the_road: list[UUID] = ()
    # Vans broken down.
    broken_down: list[UUID] = ()

    def __bool__(self) -> bool:
        return bool(self.detail())

    def detail(self) -> dict[str, list[str]]:
        """For a failed job's error text: only the lists that are not empty.
        The API's error bodies are built in routers/optimisation_jobs.py."""
        lists = {
            "pickup_request_ids_on_departed_routes": self.departed,
            "pickup_request_ids_left_behind": self.left_behind,
            "pickup_request_ids_not_plannable": self.not_plannable,
            "vehicle_ids_on_departed_routes": self.on_the_road,
            "vehicle_ids_broken_down": self.broken_down,
        }
        return {key: sorted(map(str, ids)) for key, ids in lists.items() if ids}


class RouteConflictError(Exception):
    """The plan changed while the job queued or ran (see RouteConflicts)."""

    def __init__(self, conflicts: RouteConflicts) -> None:
        super().__init__(f"route conflicts: {conflicts.detail()}")
        self.conflicts = conflicts


class JobStore(Protocol):
    async def profile_role(self, user_id: UUID) -> str | None: ...

    async def job_for_key(self, idempotency_key: str) -> KeyedJob | None: ...

    async def pickups(self, ids: list[UUID]) -> dict[UUID, StoredPickup]: ...

    async def vehicles(self, ids: list[UUID]) -> dict[UUID, StoredVehicle]: ...

    async def route_conflicts(
        self, pickup_ids: list[UUID], vehicle_ids: list[UUID], now: datetime, breakdown: bool
    ) -> RouteConflicts: ...

    async def create_job(
        self, idempotency_key: str, request_hash: str, trigger_type: OptimizationTriggerType
    ) -> KeyedJob: ...

    async def mark_running(self, job_id: UUID) -> None: ...

    async def complete(
        self,
        job_id: UUID,
        outcome: SolveOutcome,
        vehicle_ids: list[UUID],
        now: datetime,
        breakdown: bool,
    ) -> None: ...

    async def fail(self, job_id: UUID, error: str) -> None: ...

    async def fail_unfinished(self) -> int: ...

    async def result(self, job_id: UUID) -> OptimisationJobResult | None: ...


# A route has departed once its van was due to leave the depot, once a
# pickup on it is recorded (confirmed or an exception: the van left early),
# or once it is completed. Before that it can still be replaced. $2 is now.
_DEPARTED_ROUTE = """
    r.status = 'completed'
    or r.planned_departure <= $2
    or exists (
        select 1 from public.route_nodes rn
        join public.pickup_events e on e.route_node_id = rn.id
        where rn.route_id = r.id
    )
"""

# A departed route stays as it is, except in a vehicle_breakdown re-plan
# ($3) when its van has broken down: then its pickups not yet collected may
# be re-planned onto other vans.
_FIXED_ROUTE = f"""
    ({_DEPARTED_ROUTE})
    and not ($3::boolean and exists (
        select 1 from public.vehicles v
        where v.id = r.vehicle_id and v.status = 'broken_down'
    ))
"""

# Live nodes of the pickups ($1) on routes still in use.
_LIVE_NODES = """
    from public.route_nodes n
    join public.routes r on r.id = n.route_id
    where n.pickup_request_id = any($1::uuid[])
      and n.superseded_at is null
      and r.status in ('active', 'completed')
"""

# The routes a job over pickups $1 and vans $3 replaces, at $2: every active
# route holding a live node of a pickup in $1, and every active route of a
# van in $3 that has not departed. Taking the vans' routes too means a van
# never has two active routes: its route that has not left is re-planned
# with the job (a departed one keeps the van out of the job, _ON_THE_ROAD).
_REPLACED_ROUTES = f"""
    select n.route_id
    from public.route_nodes n
    join public.routes r on r.id = n.route_id
    where n.pickup_request_id = any($1::uuid[])
      and n.superseded_at is null
      and r.status = 'active'
    union
    select r.id
    from public.routes r
    where r.vehicle_id = any($3::uuid[])
      and r.status = 'active'
      and not ({_DEPARTED_ROUTE})
"""

# Vans ($1) on the road at $2: an active route of theirs has departed and
# is not yet due back at JKIA plus the grace period ($3). A completed route
# is not active, so its van is free again.
_ON_THE_ROAD = """
    select distinct r.vehicle_id
    from public.routes r
    where r.vehicle_id = any($1::uuid[])
      and r.status = 'active'
      and (
          r.planned_departure <= $2
          or exists (
              select 1 from public.route_nodes rn
              join public.pickup_events e on e.route_node_id = rn.id
              where rn.route_id = r.id
          )
      )
      and $2 < r.planned_arrival + $3::interval
    order by r.vehicle_id
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
    def __init__(self, pool: asyncpg.Pool, depot: Point, van_return_grace: timedelta) -> None:
        self._pool = pool
        self._depot = depot
        self._grace = van_return_grace

    async def profile_role(self, user_id: UUID) -> str | None:
        """profiles.role of a verified caller (#127), or None without a
        profile. As postgres, like the rest of the job API: the dispatcher's
        RLS policies would allow everything it reads anyway."""
        return await self._pool.fetchval("select role from public.profiles where id = $1", user_id)

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
            "select id, capacity, status from public.vehicles where id = any($1::uuid[])", ids
        )
        return {r["id"]: StoredVehicle(r["id"], r["capacity"], r["status"]) for r in rows}

    async def route_conflicts(
        self, pickup_ids: list[UUID], vehicle_ids: list[UUID], now: datetime, breakdown: bool
    ) -> RouteConflicts:
        return await _route_conflicts(
            self._pool, pickup_ids, vehicle_ids, now, breakdown, self._grace
        )

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

    async def complete(
        self,
        job_id: UUID,
        outcome: SolveOutcome,
        vehicle_ids: list[UUID],
        now: datetime,
        breakdown: bool,
    ) -> None:
        """Write the plan and complete the job in one transaction, so a job is
        never completed without its routes, and a failure leaves nothing.
        vehicle_ids are the job's vans, used or not, as the API checked them."""
        routed = [UUID(s.pickup_id) for route in outcome.routes for s in route.stops]
        requested = routed + [UUID(i) for i in outcome.unassigned]
        vans = vehicle_ids
        async with self._pool.acquire() as conn, conn.transaction():
            # Lock the job's pickups before checking them. A pickup event's
            # status change (023) then either waits for this transaction,
            # and 025 drops the node written here, or this waits for it and
            # the check below sees the pickup collected. Either way a pickup
            # collected while the job ran never keeps a new live node.
            await conn.execute(
                """
                select 1 from public.pickup_requests
                where id = any($1::uuid[]) order by id for update
                """,
                requested,
            )
            # The API checked this when the job was accepted, with the same
            # pickups and vans. While the job queued or ran, a route may have
            # left, a van may have left, broken down or been given a route, a
            # pickup may have been collected (and 025 taken it off its route),
            # or another job may have changed the plan.
            conflicts = await _route_conflicts(conn, requested, vans, now, breakdown, self._grace)
            if conflicts:
                raise RouteConflictError(conflicts)

            # Supersede the job's pickups' live nodes, and every other live
            # node of the routes it replaces (its pickups' and its vans'), so
            # those routes are replaced whole. The pickups left on such a
            # route are past assigned (the check above found no plannable
            # ones): they get no new node.
            # Except a node with an event of its own, which only a broken-down
            # van's route can have here: what that van collected (or found
            # missing) keeps its node, as the record of what happened.
            old_routes = await conn.fetch(
                f"""
                update public.route_nodes n
                set superseded_at = $2
                where n.superseded_at is null
                  and (n.pickup_request_id = any($1::uuid[])
                       or (n.route_id in ({_REPLACED_ROUTES})
                           and not exists (
                               select 1 from public.pickup_events e
                               where e.route_node_id = n.id
                           )))
                returning n.route_id
                """,
                requested,
                now,
                vans,
            )
            # A replaced route with no live node left is superseded; a
            # broken-down van's route that keeps a collected pickup stays.
            await conn.execute(
                """
                update public.routes r set status = 'superseded'
                where r.id = any($1::uuid[]) and r.status = 'active'
                  and not exists (
                      select 1 from public.route_nodes n
                      where n.route_id = r.id and n.superseded_at is null
                  )
                """,
                list({r["route_id"] for r in old_routes}),
            )

            for route in outcome.routes:
                route_id = await conn.fetchval(
                    """
                    insert into public.routes
                        (vehicle_id, optimization_job_id, total_distance_km,
                         planned_departure, planned_arrival)
                    values ($1, $2, 0, $3, $4)
                    returning id
                    """,
                    UUID(route.vehicle_id),
                    job_id,
                    route.departure,
                    route.arrival,
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
                r.planned_departure, r.planned_arrival,
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
                    planned_departure=n["planned_departure"],
                    planned_arrival=n["planned_arrival"],
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


async def _route_conflicts(
    conn: asyncpg.Pool | asyncpg.Connection,
    pickup_ids: list[UUID],
    vehicle_ids: list[UUID],
    now: datetime,
    breakdown: bool,
    grace: timedelta,
) -> RouteConflicts:
    departed = await conn.fetch(
        f"select n.pickup_request_id {_LIVE_NODES} and ({_FIXED_ROUTE}) "
        "order by n.pickup_request_id",
        pickup_ids,
        now,
        breakdown,
    )
    left_behind = await conn.fetch(
        f"""
        select distinct other.pickup_request_id
        from public.route_nodes other
        join public.pickup_requests p on p.id = other.pickup_request_id
        where other.route_id in ({_REPLACED_ROUTES})
          and other.superseded_at is null
          and not other.pickup_request_id = any($1::uuid[])
          and p.status in ('pending', 'assigned')
        order by other.pickup_request_id
        """,
        pickup_ids,
        now,
        vehicle_ids,
    )
    not_plannable = await conn.fetch(
        """
        select id from public.pickup_requests
        where id = any($1::uuid[]) and status not in ('pending', 'assigned')
        order by id
        """,
        pickup_ids,
    )
    on_the_road = await conn.fetch(_ON_THE_ROAD, vehicle_ids, now, grace)
    broken_down = await conn.fetch(
        """
        select id from public.vehicles
        where id = any($1::uuid[]) and status = 'broken_down'
        order by id
        """,
        vehicle_ids,
    )
    return RouteConflicts(
        [r["pickup_request_id"] for r in departed],
        [r["pickup_request_id"] for r in left_behind],
        [r["id"] for r in not_plannable],
        [r["vehicle_id"] for r in on_the_road],
        [r["id"] for r in broken_down],
    )


async def connect(database_url: str) -> asyncpg.Pool:
    # No prepared statement cache: Supabase's transaction pooler (port 6543)
    # hands each statement to any server connection, where a statement
    # prepared on another one does not exist. Harmless on the session pooler.
    return await asyncpg.create_pool(database_url, statement_cache_size=0, min_size=1, max_size=5)
