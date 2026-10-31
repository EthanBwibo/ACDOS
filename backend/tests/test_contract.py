"""The committed API contract, docs/openapi.json (#122), and the errors it
declares.

- The committed file is what the code generates now (the staleness check
  CI runs, as part of pytest).
- It is the same bytes whatever the environment.
- Every 4xx/5xx it declares is the one ErrorBody, with its codes.
- Bearer auth is declared exactly where a token is checked.
- Every route really sends every error code it declares, in that body, and
  sends no error it does not declare (the two cannot drift apart).
"""

import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app import contract, reads
from app.config import settings
from app.errors import ErrorBody, ErrorCode
from app.jobs.runner import JobRunner
from app.jobs.store import StoredPickup, StoredVehicle
from app.main import app
from app.solver.problem import Point
from tests.fake_job_store import FakeJob, InMemoryJobStore
from tests.jwt_keys import ISSUER, FakeJwks, SigningKey, bearer

BACKEND = Path(__file__).resolve().parents[1]
SPEC = json.loads(contract.openapi_json())
KEY = SigningKey("contract-key")
NOW = datetime(2026, 11, 2, tzinfo=UTC)
TOKEN_ROUTES = {
    "/drivers/me/route",
    "/drivers/me/routes",
    "/crew/me/pickup",
    "/optimisation-jobs",
    "/optimisation-jobs/{job_id}",
    "/drivers/me/pickup-events",
}
DISPATCHER, CREW_USER = uuid4(), uuid4()  # profiles.role in the fake job store


def operations():
    for path, ops in SPEC["paths"].items():
        for method, op in ops.items():
            yield method.upper(), path, op


def declared_errors() -> set[tuple[str, str, int, str]]:
    return {
        (method, path, int(status), code)
        for method, path, op in operations()
        for status, response in op["responses"].items()
        if status[0] in "45"
        for code in response["x-error-codes"]
    }


# --- The file and its stability -------------------------------------------


def test_committed_contract_is_current():
    assert contract.is_current(), f"docs/openapi.json is stale. Run: {contract.REGENERATE}"


def test_contract_is_the_same_whatever_the_environment():
    code = "from app import contract; import sys; sys.stdout.write(contract.openapi_json())"
    digests = set()
    for env in [
        {"PYTHONHASHSEED": "1"},
        {"PYTHONHASHSEED": "2"},
        {"PYTHONHASHSEED": "3", "APP_NAME": "Something else", "TRAVEL_MODEL": "haversine"},
    ]:
        run = subprocess.run(
            [sys.executable, "-c", code],
            cwd=BACKEND,
            capture_output=True,
            env=os.environ | env,
            check=True,
        )
        digests.add(hashlib.sha256(run.stdout).hexdigest())
    assert len(digests) == 1


# --- What the contract declares -------------------------------------------


def test_every_error_response_is_the_one_envelope():
    schemas = SPEC["components"]["schemas"]
    assert "HTTPValidationError" not in schemas  # FastAPI's own 422 body is gone
    assert schemas["ErrorCode"]["enum"] == [c.value for c in ErrorCode]
    for method, path, op in operations():
        for status, response in op["responses"].items():
            if status[0] not in "45":
                continue
            where = f"{method} {path} {status}"
            schema = response["content"]["application/json"]["schema"]
            assert schema == {"$ref": "#/components/schemas/ErrorBody"}, where
            assert response["x-error-codes"], where
            assert set(response["x-error-codes"]) <= {c.value for c in ErrorCode}, where


def test_bearer_auth_is_declared_exactly_where_a_token_is_checked():
    assert SPEC["components"]["securitySchemes"] == {
        "bearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "The Supabase session access token.",
        }
    }
    secured = {path for _, path, op in operations() if op.get("security")}
    assert secured == TOKEN_ROUTES
    for _, path, op in operations():
        if path in TOKEN_ROUTES:
            assert op["security"] == [{"bearerAuth": []}]


# --- Every declared error, really sent ------------------------------------


@dataclass
class World:
    client: TestClient
    store: InMemoryJobStore
    monkeypatch: pytest.MonkeyPatch

    def token(self) -> dict:
        return bearer(KEY.token(uuid4()))

    def dispatcher(self) -> dict:
        """The job API's caller (#127)."""
        return bearer(KEY.token(DISPATCHER))

    def without_runner(self) -> None:
        self.monkeypatch.setattr(app.state, "job_runner", None)

    def without_db(self) -> None:
        self.monkeypatch.setattr(app.state, "db", None, raising=False)

    def without_keys(self) -> None:
        self.monkeypatch.setattr(app.state, "jwt_keys", None, raising=False)

    def as_profile(self, role: str) -> None:
        """A database whose caller has this role (no real queries run)."""

        @asynccontextmanager
        async def as_caller(pool, user_id):
            yield None, reads.Profile(role, None)

        async def profile_of(conn, user_id):
            return reads.Profile(role, None)

        self.monkeypatch.setattr(app.state, "db", object(), raising=False)
        self.monkeypatch.setattr(reads, "as_caller", as_caller)
        self.monkeypatch.setattr(reads, "profile_of", profile_of)

    def job_body(self, **changes) -> dict:
        return {
            "trigger_type": "scheduled",
            "pickup_request_ids": [str(i) for i in self.store.stored_pickups],
            "vehicle_ids": [str(i) for i in self.store.stored_vehicles],
        } | changes

    def post_job(self, body: dict, key: str = "contract-key") -> object:
        headers = {"Idempotency-Key": key} | self.dispatcher()
        return self.client.post("/optimisation-jobs", json=body, headers=headers)


def _reused_key(w: World):
    w.store.jobs[uuid4()] = FakeJob("used-key", "another-hash")
    return w.post_job(w.job_body(), key="used-key")


def _not_plannable(w: World):
    done = next(iter(w.store.stored_pickups.values()))
    w.store.stored_pickups[done.id] = StoredPickup(
        done.id, done.location, done.report_time, "cancelled"
    )
    return w.post_job(w.job_body())


def _departed(w: World):
    w.store.departed.add(next(iter(w.store.stored_pickups)))
    return w.post_job(w.job_body())


def _left_behind(w: World):
    first, second = list(w.store.stored_pickups)[:2]
    w.store.route_mates = {first: {second}, second: {first}}
    return w.post_job(w.job_body(pickup_request_ids=[str(first)]))


def _duplicates(w: World):
    pickup = str(next(iter(w.store.stored_pickups)))
    return w.post_job(w.job_body(pickup_request_ids=[pickup, pickup]))


def _unknown(w: World):
    return w.post_job(w.job_body(vehicle_ids=[str(uuid4())]))


def _job_without_runner(method: str):
    def run(w: World):
        w.without_runner()
        if method == "POST":
            return w.post_job(w.job_body())
        return w.client.get(f"/optimisation-jobs/{uuid4()}", headers=w.dispatcher())

    return run


def _job_as(headers: Callable[[World], dict], method: str):
    def run(w: World):
        if method == "POST":
            return w.client.post(
                "/optimisation-jobs",
                json=w.job_body(),
                headers={"Idempotency-Key": "k"} | headers(w),
            )
        return w.client.get(f"/optimisation-jobs/{uuid4()}", headers=headers(w))

    return run


def _me(path: str, setup: Callable[[World], None] | None, token: bool, query: str = ""):
    def run(w: World):
        if setup:
            setup(w)
        return w.client.get(path + query, headers=w.token() if token else {})

    return run


EVENTS = "/drivers/me/pickup-events"


def _events(setup, token: bool = True, events: list | None = None, size: int | None = None):
    """POST a pickup-event batch: one valid-looking event by default, an
    explicit list, or a body padded to size bytes."""

    def run(w: World):
        if setup:
            setup(w)
        batch = {
            "events": events
            if events is not None
            else [
                {
                    "idempotency_key": "contract-event",
                    "route_node_id": str(uuid4()),
                    "driver_id": str(uuid4()),
                    "event_type": "pickup_confirmed",
                    "occurred_at": "2026-11-02T03:41:00Z",
                }
            ]
        }
        content = json.dumps(batch)
        if size is not None:
            content = content[:-1] + ', "padding": "' + "x" * size + '"}'
        headers = {"Content-Type": "application/json"} | (w.token() if token else {})
        return w.client.post(EVENTS, content=content, headers=headers)

    return run


# (method, path, status, code, how to make the route send it, ids expected)
CASES = (
    [
        ("POST", "/optimisation-jobs", 409, "departed_routes", _departed, True),
        ("POST", "/optimisation-jobs", 409, "left_behind_on_route", _left_behind, True),
        (
            "POST",
            "/optimisation-jobs",
            422,
            "validation_failed",
            lambda w: w.client.post(
                "/optimisation-jobs", json=w.job_body(), headers=w.dispatcher()
            ),
            False,
        ),
        ("POST", "/optimisation-jobs", 422, "idempotency_key_reused", _reused_key, False),
        ("POST", "/optimisation-jobs", 422, "duplicate_ids", _duplicates, True),
        ("POST", "/optimisation-jobs", 422, "unknown_ids", _unknown, True),
        ("POST", "/optimisation-jobs", 422, "not_plannable", _not_plannable, True),
        ("POST", "/optimisation-jobs", 503, "unavailable", _job_without_runner("POST"), False),
        (
            "GET",
            "/optimisation-jobs/{job_id}",
            404,
            "not_found",
            lambda w: w.client.get(f"/optimisation-jobs/{uuid4()}", headers=w.dispatcher()),
            False,
        ),
        (
            "GET",
            "/optimisation-jobs/{job_id}",
            422,
            "validation_failed",
            lambda w: w.client.get("/optimisation-jobs/not-a-uuid", headers=w.dispatcher()),
            False,
        ),
        (
            "GET",
            "/optimisation-jobs/{job_id}",
            503,
            "unavailable",
            _job_without_runner("GET"),
            False,
        ),
    ]
    + [
        case
        for method, path in [("POST", "/optimisation-jobs"), ("GET", "/optimisation-jobs/{job_id}")]
        for case in [
            (method, path, 401, "unauthorized", _job_as(lambda w: {}, method), False),
            (
                method,
                path,
                403,
                "forbidden",
                _job_as(lambda w: bearer(KEY.token(CREW_USER)), method),
                False,
            ),
        ]
    ]
    + [
        case
        for path, role in [
            ("/drivers/me/route", "crew"),
            ("/drivers/me/routes", "crew"),
            ("/crew/me/pickup", "driver"),
        ]
        for case in [
            ("GET", path, 401, "unauthorized", _me(path, None, token=False), False),
            (
                "GET",
                path,
                403,
                "forbidden",
                _me(path, lambda w, role=role: w.as_profile(role), token=True),
                False,
            ),
            ("GET", path, 503, "unavailable", _me(path, World.without_db, token=True), False),
        ]
    ]
    + [
        (
            "GET",
            "/drivers/me/routes",
            422,
            "validation_failed",
            _me("/drivers/me/routes", None, token=True, query="?cursor=not-a-cursor"),
            False,
        ),
    ]
    + [
        ("POST", EVENTS, 401, "unauthorized", _events(None, token=False), False),
        ("POST", EVENTS, 403, "forbidden", _events(lambda w: w.as_profile("crew")), False),
        ("POST", EVENTS, 413, "payload_too_large", _events(None, size=40 * 1024), False),
        ("POST", EVENTS, 422, "validation_failed", _events(None, events=[]), False),
        ("POST", EVENTS, 503, "unavailable", _events(World.without_db), False),
    ]
)


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setattr(settings, "database_url", None)
    monkeypatch.setattr(app.state, "jwt_keys", FakeJwks(KEY).source(), raising=False)
    monkeypatch.setattr(app.state, "jwt_issuer", ISSUER, raising=False)
    monkeypatch.setattr(app.state, "db", None, raising=False)
    store = InMemoryJobStore(roles={DISPATCHER: "dispatcher", CREW_USER: "crew"})
    for k in range(3):
        pickup = StoredPickup(
            uuid4(), Point(-1.27 - k / 100, 36.81), NOW + timedelta(hours=3), "pending"
        )
        store.stored_pickups[pickup.id] = pickup
    vehicle = StoredVehicle(uuid4(), 7)
    store.stored_vehicles[vehicle.id] = vehicle
    # No pool: these requests never get as far as a solve.
    runner = JobRunner(
        store, None, 1, depot=Point(-1.3192, 36.9278), time_limit_sec=1.0,
        travel_model="haversine", now=lambda: NOW,
    )  # fmt: skip
    monkeypatch.setattr(app.state, "job_runner", runner, raising=False)
    with TestClient(app) as client:
        yield World(client, store, monkeypatch)


@pytest.mark.parametrize(
    ("method", "path", "status", "code", "send", "about_ids"),
    CASES,
    ids=[f"{m} {p} {s} {c}" for m, p, s, c, _, _ in CASES],
)
def test_each_declared_error_is_sent_in_its_declared_body(
    world, method, path, status, code, send, about_ids
):
    response = send(world)

    assert response.status_code == status, response.text
    assert (method, path, status, code) in declared_errors(), "sent but not declared"
    error = ErrorBody.model_validate(response.json())  # the declared model
    assert error.code == code
    assert error.detail
    # Id lists only when the error is about ids, and never as null.
    has_ids = bool(error.pickup_request_ids or error.vehicle_ids)
    assert has_ids == about_ids
    assert None not in response.json().values()
    if status == 401:
        assert response.headers["WWW-Authenticate"] == "Bearer"


def test_every_declared_error_has_a_case():
    exercised = {(m, p, s, c) for m, p, s, c, _, _ in CASES}
    assert declared_errors() == exercised


def per_event_codes() -> set[str]:
    """The codes a pickup event can be rejected with (#33), declared on the
    result's code field."""
    field = SPEC["components"]["schemas"]["PickupEventResult"]["properties"]["code"]
    return set(field["x-error-codes"])


def test_every_error_code_is_used_by_some_route_or_the_framework():
    used = {code for *_, code in declared_errors()} | per_event_codes()
    framework_only = {ErrorCode.METHOD_NOT_ALLOWED}  # tested below; no route declares it
    assert used | framework_only == {c.value for c in ErrorCode}


def test_per_event_codes_are_real_error_codes():
    # Each is driven against Postgres in test_pickup_events_postgres.py.
    assert per_event_codes() <= {c.value for c in ErrorCode}


def test_unknown_paths_and_methods_use_the_envelope_too(world):
    not_found = world.client.get("/no-such-path")
    wrong_method = world.client.delete("/health")

    assert (not_found.status_code, not_found.json()["code"]) == (404, "not_found")
    assert (wrong_method.status_code, wrong_method.json()["code"]) == (405, "method_not_allowed")
