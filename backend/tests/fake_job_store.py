"""In-memory JobStore for the API tests that need no database.

Keeps what the API reads back: jobs, their status and their outcome. The
SQL itself (routes, supersede, distances) is tested against Postgres in
test_optimisation_jobs_postgres.py.
"""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4

from app.jobs.store import KeyedJob, RouteConflicts, StoredPickup, StoredVehicle
from app.jobs.worker import SolveOutcome
from app.models.schemas import (
    LatePickup,
    OptimisationJobResult,
    OptimizationJobStatus,
    OptimizationTriggerType,
    PlannedNode,
    PlannedRoute,
)


@dataclass
class FakeJob:
    idempotency_key: str
    request_hash: str
    status: OptimizationJobStatus = OptimizationJobStatus.QUEUED
    error: str | None = None
    outcome: SolveOutcome | None = None
    # complete()'s breakdown flag: True for a vehicle_breakdown re-plan.
    breakdown: bool | None = None


@dataclass
class InMemoryJobStore:
    stored_pickups: dict[UUID, StoredPickup] = field(default_factory=dict)
    stored_vehicles: dict[UUID, StoredVehicle] = field(default_factory=dict)
    # Pickups on a route that has left.
    departed: set[UUID] = field(default_factory=set)
    # Pickup -> the other plannable pickups on its active route.
    route_mates: dict[UUID, set[UUID]] = field(default_factory=dict)
    # Vans on a route that has left.
    on_the_road: set[UUID] = field(default_factory=set)
    # The breakdown flag of each route_conflicts call, in order.
    breakdown_asked: list[bool] = field(default_factory=list)
    jobs: dict[UUID, FakeJob] = field(default_factory=dict)
    # profiles.role by user id (#127).
    roles: dict[UUID, str] = field(default_factory=dict)

    async def profile_role(self, user_id: UUID) -> str | None:
        return self.roles.get(user_id)

    async def job_for_key(self, idempotency_key: str) -> KeyedJob | None:
        for job_id, job in self.jobs.items():
            if job.idempotency_key == idempotency_key:
                return KeyedJob(job_id, job.request_hash)
        return None

    async def pickups(self, ids: list[UUID]) -> dict[UUID, StoredPickup]:
        return {i: self.stored_pickups[i] for i in ids if i in self.stored_pickups}

    async def vehicles(self, ids: list[UUID]) -> dict[UUID, StoredVehicle]:
        return {i: self.stored_vehicles[i] for i in ids if i in self.stored_vehicles}

    async def route_conflicts(
        self, pickup_ids: list[UUID], vehicle_ids: list[UUID], now: datetime, breakdown: bool
    ) -> RouteConflicts:
        self.breakdown_asked.append(breakdown)
        mates = set().union(*(self.route_mates.get(i, set()) for i in pickup_ids))
        return RouteConflicts(
            sorted(i for i in pickup_ids if i in self.departed),
            sorted(mates - set(pickup_ids)),
            on_the_road=sorted(i for i in vehicle_ids if i in self.on_the_road),
        )

    async def create_job(
        self, idempotency_key: str, request_hash: str, trigger_type: OptimizationTriggerType
    ) -> KeyedJob:
        existing = await self.job_for_key(idempotency_key)
        if existing is not None:
            return existing
        job_id = uuid4()
        self.jobs[job_id] = FakeJob(idempotency_key, request_hash)
        return KeyedJob(job_id, request_hash, created=True)

    async def mark_running(self, job_id: UUID) -> None:
        self.jobs[job_id].status = OptimizationJobStatus.RUNNING

    async def complete(
        self,
        job_id: UUID,
        outcome: SolveOutcome,
        vehicle_ids: list[UUID],
        now: datetime,
        breakdown: bool,
    ) -> None:
        self.jobs[job_id].outcome = outcome
        self.jobs[job_id].breakdown = breakdown
        self.jobs[job_id].status = OptimizationJobStatus.COMPLETED

    async def fail(self, job_id: UUID, error: str) -> None:
        self.jobs[job_id].status = OptimizationJobStatus.FAILED
        self.jobs[job_id].error = error

    async def fail_unfinished(self) -> int:
        return 0

    async def result(self, job_id: UUID) -> OptimisationJobResult | None:
        job = self.jobs.get(job_id)
        if job is None:
            return None
        result = OptimisationJobResult(id=job_id, status=job.status, error=job.error)
        if job.outcome is None:
            return result
        result.routes = [
            PlannedRoute(
                vehicle_id=UUID(route.vehicle_id),
                total_distance_km=0.0,  # PostGIS's job; not modelled here
                planned_departure=route.departure,
                planned_arrival=route.arrival,
                nodes=[
                    PlannedNode(
                        pickup_request_id=UUID(stop.pickup_id),
                        seq_order=seq,
                        estimated_arrival=stop.arrival,
                    )
                    for seq, stop in enumerate(route.stops, start=1)
                ],
            )
            for route in job.outcome.routes
        ]
        result.late = [
            LatePickup(pickup_request_id=UUID(i), late_sec=late)
            for i, late in sorted(job.outcome.late_sec.items())
            if late
        ]
        result.unassigned = [UUID(i) for i in job.outcome.unassigned]
        return result
