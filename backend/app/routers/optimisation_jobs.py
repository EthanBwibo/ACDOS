"""Run an optimisation and read its plan (#51).

POST accepts a job and answers 202 straight away; the solve runs in a
solver process (app/jobs/runner.py) and the client polls GET.

Order of checks on POST, so a rejected request never creates a job row:
1. Idempotency-Key already used: same body, the job it started; a different
   body, 422.
2. Every id exists, and no pickup is past assigned: else 422.
3. No pickup is on a route that has departed, and no active route the
   request replaces carries a pickup the request leaves out: else 409 with
   the ids. #113 handles both, and re-plans that keep a route running.
4. Create the job (queued) and hand it to the runner.

Who may call this (dispatchers only) is #52.
"""

import hashlib
import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, status

from app.jobs.runner import JobRunner
from app.jobs.worker import PickupInput, VehicleInput
from app.models.schemas import (
    OptimisationJobAccepted,
    OptimisationJobCreate,
    OptimisationJobResult,
    PickupRequestStatus,
)

router = APIRouter(prefix="/optimisation-jobs", tags=["optimisation jobs"])

# A pickup in any later state (picked up, missed, cancelled) is not to be
# planned again.
PLANNABLE = {PickupRequestStatus.PENDING, PickupRequestStatus.ASSIGNED}


def runner(request: Request) -> JobRunner:
    job_runner = getattr(request.app.state, "job_runner", None)
    if job_runner is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "DATABASE_URL is not set")
    return job_runner


def request_hash(body: OptimisationJobCreate) -> str:
    """SHA-256 of the body with its id lists sorted: the same request in a
    different order is the same request."""
    canonical = {
        "trigger_type": body.trigger_type.value,
        "pickup_request_ids": sorted(map(str, body.pickup_request_ids)),
        "vehicle_ids": sorted(map(str, body.vehicle_ids)),
    }
    return hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()


def _accepted_or_422(job_id: UUID, stored_hash: str, body_hash: str) -> OptimisationJobAccepted:
    if stored_hash != body_hash:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "this Idempotency-Key was used with a different request body",
        )
    return OptimisationJobAccepted(id=job_id)


def _repeated(ids: list[UUID]) -> list[str]:
    return sorted({str(i) for i in ids if ids.count(i) > 1})


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=OptimisationJobAccepted)
async def create_job(
    request: Request,
    body: OptimisationJobCreate,
    idempotency_key: Annotated[str, Header(min_length=1, max_length=200)],
) -> OptimisationJobAccepted:
    job_runner = runner(request)
    store = job_runner.store
    body_hash = request_hash(body)

    existing = await store.job_for_key(idempotency_key)
    if existing is not None:
        return _accepted_or_422(existing.id, existing.request_hash, body_hash)

    repeated = {
        "pickup_request_ids": _repeated(body.pickup_request_ids),
        "vehicle_ids": _repeated(body.vehicle_ids),
    }
    if any(repeated.values()):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, {"listed_more_than_once": repeated}
        )

    pickups = await store.pickups(body.pickup_request_ids)
    vehicles = await store.vehicles(body.vehicle_ids)
    problems = {
        "unknown_pickup_request_ids": sorted(
            str(i) for i in body.pickup_request_ids if i not in pickups
        ),
        "unknown_vehicle_ids": sorted(str(i) for i in body.vehicle_ids if i not in vehicles),
        "pickup_request_ids_not_plannable": sorted(
            str(p.id) for p in pickups.values() if p.status not in PLANNABLE
        ),
    }
    if any(problems.values()):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, problems)

    conflicts = await store.route_conflicts(body.pickup_request_ids, job_runner.now())
    if conflicts:
        raise HTTPException(status.HTTP_409_CONFLICT, conflicts.detail())

    job = await store.create_job(idempotency_key, body_hash, body.trigger_type)
    if not job.created:
        # Another request with this key made the job since the lookup above.
        return _accepted_or_422(job.id, job.request_hash, body_hash)
    job_runner.submit(
        job.id,
        tuple(
            PickupInput(str(p.id), p.location, p.report_time)
            for p in (pickups[i] for i in body.pickup_request_ids)
        ),
        tuple(VehicleInput(str(v.id), v.capacity) for v in (vehicles[i] for i in body.vehicle_ids)),
    )
    return OptimisationJobAccepted(id=job.id)


@router.get("/{job_id}", response_model=OptimisationJobResult)
async def get_job(request: Request, job_id: UUID) -> OptimisationJobResult:
    result = await runner(request).store.result(job_id)
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such optimisation job")
    return result
