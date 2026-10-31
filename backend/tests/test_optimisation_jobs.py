"""Optimisation job API (#51), on an in-memory store.

The solve is real: a real solver process from the same pool the backend
uses, with straight-line travel and a 1 s limit to keep the tests quick.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.jobs.runner import JobRunner, solver_pool
from app.jobs.store import StoredPickup, StoredVehicle
from app.jobs.worker import PickupInput, SolveInput, VehicleInput, build_problem
from app.main import app
from app.solver.problem import Point
from tests.fake_job_store import InMemoryJobStore
from tests.job_api import individual_from_result, wait_for_job
from tests.jwt_keys import ISSUER, FakeJwks, SigningKey, bearer
from tests.solver_checks import assert_feasible

EPOCH = datetime(2026, 11, 2, 0, 0, tzinfo=UTC)  # 03:00 in Nairobi
DEPOT = Point(-1.30, 36.80)
TIME_LIMIT_SEC = 1.0
SEATS = 3

# Eight crew across Nairobi for two 3-seat vans: two can't be carried at all.
# The last one reports 5 minutes after the epoch, too soon for any van to
# reach JKIA, so the plan has to report them late or unassigned.
CREW = [
    (Point(-1.2675, 36.8120), timedelta(hours=2)),
    (Point(-1.2789, 36.7778), timedelta(hours=2, minutes=30)),
    (Point(-1.2921, 36.8219), timedelta(hours=2)),
    (Point(-1.3100, 36.8500), timedelta(hours=3)),
    (Point(-1.2200, 36.8900), timedelta(hours=3)),
    (Point(-1.3300, 36.7600), timedelta(hours=2, minutes=15)),
    (Point(-1.2500, 36.7400), timedelta(hours=3)),
    (Point(-1.2600, 36.8000), timedelta(minutes=5)),
]


@pytest.fixture(scope="module")
def pool():
    pool = solver_pool(1, "haversine")
    yield pool
    pool.shutdown(cancel_futures=True)


# Only dispatchers may use the job API (#127): every request here carries a
# dispatcher's token, signed by a key made for the test run.
KEY = SigningKey("job-api-key")
DISPATCHER = uuid4()


@pytest.fixture
def store():
    store = InMemoryJobStore(roles={DISPATCHER: "dispatcher"})
    for location, report_in in CREW:
        pickup = StoredPickup(uuid4(), location, EPOCH + report_in, "pending")
        store.stored_pickups[pickup.id] = pickup
    for _ in range(2):
        vehicle = StoredVehicle(uuid4(), SEATS)
        store.stored_vehicles[vehicle.id] = vehicle
    return store


@pytest.fixture
def client(store, pool, monkeypatch):
    monkeypatch.setattr(app.state, "jwt_keys", FakeJwks(KEY).source(), raising=False)
    monkeypatch.setattr(app.state, "jwt_issuer", ISSUER, raising=False)
    app.state.job_runner = JobRunner(
        store,
        pool,
        1,
        depot=DEPOT,
        time_limit_sec=TIME_LIMIT_SEC,
        travel_model="haversine",
        now=lambda: EPOCH,
    )
    with TestClient(app, headers=bearer(KEY.token(DISPATCHER))) as client:
        yield client
    app.state.job_runner = None


def body(store: InMemoryJobStore, **changes) -> dict:
    return {
        "trigger_type": "scheduled",
        "pickup_request_ids": [str(i) for i in store.stored_pickups],
        "vehicle_ids": [str(i) for i in store.stored_vehicles],
    } | changes


def post(client: TestClient, json: dict, key: str = "key-1"):
    return client.post("/optimisation-jobs", json=json, headers={"Idempotency-Key": key})


def test_routes_from_a_completed_job_pass_the_feasibility_check(client, store):
    accepted = post(client, body(store))
    assert accepted.status_code == 202
    result = wait_for_job(client, accepted.json()["id"])
    assert result["status"] == "completed", result["error"]

    # The same Problem the solver process built, to judge the returned plan.
    problem = build_problem(
        SolveInput(
            tuple(
                PickupInput(str(p.id), p.location, p.report_time)
                for p in store.stored_pickups.values()
            ),
            tuple(VehicleInput(str(v.id), v.capacity) for v in store.stored_vehicles.values()),
            DEPOT,
            EPOCH,
            TIME_LIMIT_SEC,
            "haversine",
            seed=0,
        )
    )
    late = assert_feasible(problem, individual_from_result(problem, result))

    # Every missed deadline is reported: the late ones with their lateness,
    # rounded up to whole seconds, the rest as unassigned.
    assert {UUID(p["pickup_request_id"]): p["late_sec"] for p in result["late"]} == {
        UUID(i): pytest.approx(sec, abs=1) for i, sec in late.items() if sec > 0
    }
    assert len(result["unassigned"]) >= len(CREW) - 2 * SEATS


def test_same_idempotency_key_returns_the_same_job(client, store):
    first = post(client, body(store))
    # The same request again, ids in another order: still the same request.
    reordered = body(store, vehicle_ids=[str(i) for i in reversed(store.stored_vehicles)])
    second = post(client, reordered)

    assert first.status_code == second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    assert len(store.jobs) == 1
    wait_for_job(client, first.json()["id"])


def test_same_idempotency_key_with_a_different_body_is_refused(client, store):
    first = post(client, body(store))
    other = post(client, body(store, trigger_type="flight_delay"))

    assert other.status_code == 422
    assert len(store.jobs) == 1
    wait_for_job(client, first.json()["id"])


def test_unknown_job_id_returns_404(client):
    response = client.get(f"/optimisation-jobs/{uuid4()}")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_missing_idempotency_key_is_refused(client, store):
    response = client.post("/optimisation-jobs", json=body(store))
    assert response.status_code == 422
    assert response.json()["code"] == "validation_failed"
    assert "Idempotency-Key" in response.json()["detail"]
    assert store.jobs == {}


def test_unknown_ids_are_listed_and_create_no_job(client, store):
    missing_pickup, missing_vehicle = uuid4(), uuid4()
    request = body(store)
    request["pickup_request_ids"].append(str(missing_pickup))
    request["vehicle_ids"].append(str(missing_vehicle))

    response = post(client, request)

    assert response.status_code == 422
    error = response.json()
    assert error["code"] == "unknown_ids"
    assert error["pickup_request_ids"] == [str(missing_pickup)]
    assert error["vehicle_ids"] == [str(missing_vehicle)]
    assert store.jobs == {}


@pytest.mark.parametrize("status", ["picked_up", "missed", "cancelled"])
def test_pickups_past_assigned_are_refused(client, store, status):
    done = next(iter(store.stored_pickups.values()))
    store.stored_pickups[done.id] = StoredPickup(done.id, done.location, done.report_time, status)

    response = post(client, body(store))

    assert response.status_code == 422
    error = response.json()
    assert (error["code"], error["pickup_request_ids"]) == ("not_plannable", [str(done.id)])
    assert "vehicle_ids" not in error  # id lists only when the error is about them
    assert store.jobs == {}


def test_pickup_on_a_departed_route_is_a_conflict(client, store):
    on_the_road = next(iter(store.stored_pickups))
    store.departed.add(on_the_road)

    response = post(client, body(store))

    assert response.status_code == 409
    error = response.json()
    assert set(error) == {"code", "detail", "pickup_request_ids"}
    assert (error["code"], error["pickup_request_ids"]) == ("departed_routes", [str(on_the_road)])
    assert store.jobs == {}


def test_leaving_a_route_mate_behind_is_a_conflict(client, store):
    first, second, *rest = store.stored_pickups
    # first and second share an active route; the request leaves second out.
    store.route_mates = {first: {second}, second: {first}}

    response = post(client, body(store, pickup_request_ids=[str(first), *map(str, rest)]))

    assert response.status_code == 409
    error = response.json()
    assert (error["code"], error["pickup_request_ids"]) == ("left_behind_on_route", [str(second)])
    assert store.jobs == {}


def test_without_a_database_the_job_endpoints_are_unavailable(monkeypatch):
    monkeypatch.setattr(settings, "database_url", None)
    monkeypatch.setattr(app.state, "jwt_keys", FakeJwks(KEY).source(), raising=False)
    monkeypatch.setattr(app.state, "jwt_issuer", ISSUER, raising=False)
    with TestClient(app, headers=bearer(KEY.token(DISPATCHER))) as client:
        assert client.get(f"/optimisation-jobs/{uuid4()}").status_code == 503
