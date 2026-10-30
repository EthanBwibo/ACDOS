"""Run an optimisation and read its plan (#51).

POST accepts a job and answers 202 straight away; the solve runs in a
solver process (app/jobs/runner.py) and the client polls GET.

Order of checks on POST, so a rejected request never creates a job row.
Each error is one ErrorBody (app/errors.py) with one code; when a request
has several problems, the first in this order is reported:
1. Idempotency-Key already used: same body, the job it started; a different
   body, 422 idempotency_key_reused.
2. An id listed twice: 422 duplicate_ids. An id that doesn't exist: 422
   unknown_ids. A pickup past assigned: 422 not_plannable.
3. A pickup on a route that has departed: 409 departed_routes. An active
   route the request replaces carrying a pickup the request leaves out: 409
   left_behind_on_route. #113 handles both, and re-plans that keep a route
   running.
4. Create the job (queued) and hand it to the runner.

Who may call this (dispatchers only) is #52.
"""

import hashlib
import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Request, status

from app.errors import ApiError, ErrorCode, errors
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
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE, ErrorCode.UNAVAILABLE, "DATABASE_URL is not set"
        )
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
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ErrorCode.IDEMPOTENCY_KEY_REUSED,
            "this Idempotency-Key was used with a different request body",
        )
    return OptimisationJobAccepted(id=job_id)


def _repeated(ids: list[UUID]) -> list[UUID]:
    return sorted({i for i in ids if ids.count(i) > 1}, key=str)


def _422(code: ErrorCode, detail: str, **ids: list[UUID]) -> ApiError:
    return ApiError(
        status.HTTP_422_UNPROCESSABLE_CONTENT, code, detail, **{k: v for k, v in ids.items() if v}
    )


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=OptimisationJobAccepted,
    responses=errors(
        {
            409: [ErrorCode.DEPARTED_ROUTES, ErrorCode.LEFT_BEHIND_ON_ROUTE],
            422: [
                ErrorCode.VALIDATION_FAILED,
                ErrorCode.IDEMPOTENCY_KEY_REUSED,
                ErrorCode.DUPLICATE_IDS,
                ErrorCode.UNKNOWN_IDS,
                ErrorCode.NOT_PLANNABLE,
            ],
            503: [ErrorCode.UNAVAILABLE],
        }
    ),
)
async def create_job(
    request: Request,
    body: OptimisationJobCreate,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)],
) -> OptimisationJobAccepted:
    job_runner = runner(request)
    store = job_runner.store
    body_hash = request_hash(body)

    existing = await store.job_for_key(idempotency_key)
    if existing is not None:
        return _accepted_or_422(existing.id, existing.request_hash, body_hash)

    pickups_twice, vehicles_twice = _repeated(body.pickup_request_ids), _repeated(body.vehicle_ids)
    if pickups_twice or vehicles_twice:
        raise _422(
            ErrorCode.DUPLICATE_IDS,
            "these ids are listed more than once",
            pickup_request_ids=pickups_twice,
            vehicle_ids=vehicles_twice,
        )

    pickups = await store.pickups(body.pickup_request_ids)
    vehicles = await store.vehicles(body.vehicle_ids)
    unknown_pickups = [i for i in body.pickup_request_ids if i not in pickups]
    unknown_vehicles = [i for i in body.vehicle_ids if i not in vehicles]
    if unknown_pickups or unknown_vehicles:
        raise _422(
            ErrorCode.UNKNOWN_IDS,
            "these ids do not exist",
            pickup_request_ids=unknown_pickups,
            vehicle_ids=unknown_vehicles,
        )
    done = [p.id for p in pickups.values() if p.status not in PLANNABLE]
    if done:
        raise _422(
            ErrorCode.NOT_PLANNABLE,
            "these pickups are past assigned (picked up, missed or cancelled)",
            pickup_request_ids=done,
        )

    conflicts = await store.route_conflicts(body.pickup_request_ids, job_runner.now())
    if conflicts.departed:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            ErrorCode.DEPARTED_ROUTES,
            "these pickups are on a route that has departed; re-planning them is #113",
            pickup_request_ids=conflicts.departed,
        )
    if conflicts.left_behind:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            ErrorCode.LEFT_BEHIND_ON_ROUTE,
            "these pickups share an active route with requested ones: include them, "
            "or leave the route alone",
            pickup_request_ids=conflicts.left_behind,
        )

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


@router.get(
    "/{job_id}",
    response_model=OptimisationJobResult,
    responses=errors(
        {
            404: [ErrorCode.NOT_FOUND],
            422: [ErrorCode.VALIDATION_FAILED],
            503: [ErrorCode.UNAVAILABLE],
        }
    ),
)
async def get_job(request: Request, job_id: UUID) -> OptimisationJobResult:
    result = await runner(request).store.result(job_id)
    if result is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "no such optimisation job")
    return result
